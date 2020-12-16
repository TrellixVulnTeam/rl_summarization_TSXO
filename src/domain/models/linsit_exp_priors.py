from src.domain.loader_utils import TextDataCollator
from src.domain.linsit import LinSITExpPriorsProcess

import pytorch_lightning as pl
import torch
from torch.utils.data import DataLoader
import numpy as np
from torch.optim.lr_scheduler import ReduceLROnPlateau
from itertools import product
import os
import torch.multiprocessing as mp
import pickle

import resource

rlimit = resource.getrlimit(resource.RLIMIT_NOFILE)
resource.setrlimit(resource.RLIMIT_NOFILE, (2048, rlimit[1]))


class LinSITExpPriors(pl.LightningModule):
    def __init__(self, dataset, reward, hparams):
        super(LinSITExpPriors, self).__init__()
        self.fields = dataset.fields
        self.pad_idx = dataset.pad_idx
        self.reward_builder = reward

        self.embedding_dim = dataset.embedding_dim
        self.pad_idx = dataset.pad_idx
        self.splits = dataset.get_splits()
        self.n_epochs_done = 0

        self.train_batch_size = hparams.train_batch_size
        self.test_batch_size = hparams.test_batch_size
        self.hidden_dim = hparams.hidden_dim
        self.decoder_dim = hparams.decoder_dim
        self.learning_rate = hparams.learning_rate
        self.epsilon = hparams.epsilon
        self.n_sents_per_summary = hparams.n_sents_per_summary
        self.dropout = hparams.dropout
        self.weight_decay = hparams.weight_decay
        self.pretraining_path = hparams.pretraining_path
        self.log_path = hparams.log_path
        self.n_mcts_samples = hparams.n_mcts_samples
        self.batch_idx = 0

        os.makedirs(self.log_path, exist_ok=True)
        self.__build_model(dataset)
        self.model = RLSummModel(hparams.hidden_dim, hparams.decoder_dim, self.dropout,)

        mp.set_start_method("forkserver", force=True)
        mp.set_sharing_strategy("file_system")

        if hparams.n_jobs_for_mcts == -1:
            self.n_processes = os.cpu_count()
        else:
            self.n_processes = hparams.n_jobs_for_mcts
        self.pool = mp.Pool(processes=self.n_processes)

    def __build_model(self, dataset):
        self.embeddings = torch.nn.Embedding.from_pretrained(
            dataset.vocab.vectors, freeze=False, padding_idx=self.pad_idx
        )
        self.wl_encoder = torch.nn.LSTM(
            input_size=self.embedding_dim,
            hidden_size=self.hidden_dim,
            num_layers=2,
            bidirectional=True,
            batch_first=True,
            dropout=self.dropout,
        )

    def word_level_encoding(self, contents):
        valid_tokens = ~(contents == self.pad_idx)
        sentences_len = valid_tokens.sum(dim=-1)
        valid_sentences = sentences_len > 0
        contents = self.embeddings(contents)
        orig_shape = contents.shape
        contents = self.wl_encoder(contents.view(-1, *orig_shape[2:]))[0].reshape(
            *orig_shape[:3], -1
        )
        contents = contents * valid_tokens.unsqueeze(-1)
        contents = contents.sum(-2)
        word_level_encodings = torch.zeros_like(contents)
        word_level_encodings[valid_sentences] = contents[
            valid_sentences
        ] / sentences_len[valid_sentences].unsqueeze(-1)
        return word_level_encodings, valid_sentences

    def __extract_features(self, contents):
        contents, valid_sentences = self.word_level_encoding(contents)
        sent_contents = self.model.sentence_level_encoding(contents)
        affinities = self.model.produce_affinities(sent_contents)
        affinities = affinities * valid_sentences

        return affinities, valid_sentences, sent_contents

    def linsit_exp_priors(
        self, sent_contents, greedy_priors, all_prior_choices, scorers, ids, c_pucts,
    ):
        results = self.pool.map(
            LinSITExpPriorsProcess(n_samples=self.n_mcts_samples,),
            product(
                zip(
                    sent_contents,
                    greedy_priors,
                    all_prior_choices,
                    [s.scores for s in scorers],
                    ids,
                ),
                c_pucts,
                [0.0, 0.1, 0.2, 0.3, 0.4, 0.5],
            ),
        )

        return [r for res in results for r in res]

    def forward(self, batch, subset):
        (
            raw_contents,
            contents,
            raw_abstracts,
            abstracts,
            ids,
            scorers,
            n_grams_dense,
        ) = batch
        batch_size = len(contents)

        torch.set_grad_enabled(False)

        self.wl_encoder.flatten_parameters()
        self.model.sl_encoder.flatten_parameters()

        c_pucts = np.logspace(4, 8, 5)

        valid_tokens = ~(contents == self.pad_idx)
        sentences_len = valid_tokens.sum(dim=-1)
        valid_sentences = sentences_len > 0

        prior_choices = ["best", "med", "worst"]
        greedy_priors, all_prior_choices = self.sample_greedy_priors(
            batch_size, valid_sentences, prior_choices, scorers
        )

        results = self.linsit_exp_priors(
            n_grams_dense, greedy_priors, all_prior_choices, scorers, ids, c_pucts,
        )

        keys = [res[0] for res in results]
        theta_hat_predictions = [res[1].cpu().numpy() for res in results]

        return keys, theta_hat_predictions

    def sample_greedy_priors(self, batch_size, valid_sentences, prior_choices, scorers):
        greedy_priors = torch.zeros(
            (batch_size, len(prior_choices), valid_sentences.shape[-1]),
            dtype=torch.float32,
            device=valid_sentences.device,
        )
        all_prior_choices = [prior_choices] * batch_size

        for batch_idx, (val_sents, scorer) in enumerate(zip(valid_sentences, scorers)):
            n_sents = val_sents.sum()
            for sample_idx, prior_choice in enumerate(prior_choices):
                s = scorer.scores.mean(-1)[:n_sents, :n_sents, :n_sents]
                if prior_choice == "best":
                    selected_sents = np.array(np.unravel_index(s.argmax(), s.shape))
                elif prior_choice == "worst":
                    s_pos = np.ma.masked_less_equal(s, 0)
                    selected_sents = np.array(
                        np.unravel_index(s_pos.argmin(), s_pos.shape)
                    )
                else:
                    # Get median
                    selected_sents = np.array(
                        [
                            a[0]
                            for a in np.nonzero(
                                s == np.percentile(s, 50, interpolation="nearest")
                            )
                        ]
                    )
                selected_sents = torch.from_numpy(selected_sents)
                greedy_priors[batch_idx][sample_idx][selected_sents] = 1 / 3

        return greedy_priors, all_prior_choices

    def get_step_output(self, loss, greedy_rewards, generated_rewards):
        output_dict = {}

        log_dict = {
            "greedy_rouge_1": greedy_rewards[:, 0].mean(),
            "greedy_rouge_2": greedy_rewards[:, 1].mean(),
            "greedy_rouge_L": greedy_rewards[:, 2].mean(),
            "greedy_rouge_mean": greedy_rewards.mean(-1).mean(),
            "generated_rouge_1": generated_rewards[:, 0].mean(),
            "generated_rouge_2": generated_rewards[:, 1].mean(),
            "generated_rouge_L": generated_rewards[:, 2].mean(),
            "generated_rouge_mean": generated_rewards.mean(-1).mean(),
        }
        log_dict["loss"] = loss

        output_dict["log"] = log_dict

        if "loss" in log_dict:
            output_dict["loss"] = log_dict["loss"]

        tqdm_keys = ["greedy_rouge", "generated_rouge"]
        output_dict["progress_bar"] = {k: log_dict[f"{k}_mean"] for k in tqdm_keys}

        return output_dict

    def training_step(self, batch, batch_idx):
        generated_rewards, loss, greedy_rewards = self.forward(batch, subset="train")

        return self.get_step_output(
            loss=loss.to(self.device),
            greedy_rewards=greedy_rewards.to(self.device),
            generated_rewards=generated_rewards.to(self.device),
        )

    def validation_step(self, batch, batch_idx):
        greedy_rewards = self.forward(batch, subset="val")

        reward_dict = {
            "val_greedy_rouge_1": greedy_rewards[:, 0],
            "val_greedy_rouge_2": greedy_rewards[:, 1],
            "val_greedy_rouge_L": greedy_rewards[:, 2],
            "val_greedy_rouge_mean": greedy_rewards.mean(-1),
        }

        return reward_dict

    def validation_step_end(self, outputs):
        for vals in outputs.values():
            vals = vals.mean()

        return outputs

    def validation_epoch_end(self, outputs):
        output_dict = self.generic_epoch_end(outputs)

        self.lr_scheduler.step(output_dict["log"]["val_greedy_rouge_mean"])

        output_dict["log"]["learning_rate"] = self.trainer.optimizers[0].param_groups[
            1
        ]["lr"]

        return output_dict

    def test_step(self, batch, batch_idx):
        keys, theta_hat_predictions = self.forward(batch, subset="test")

        d = {}

        for key, preds in zip(keys, theta_hat_predictions):
            d[key] = preds

        with open(os.path.join(self.log_path, f"results_{batch_idx}.pck"), "wb") as f:
            pickle.dump(d, f)

    def test_step_end(self, outputs):
        pass

    def generic_epoch_end(self, outputs, is_test=False):
        combined_outputs = {}
        log_dict = {}

        for key in outputs[0]:
            log_dict[key] = torch.hstack([output[key] for output in outputs]).mean()

        combined_outputs["log"] = log_dict

        if is_test:
            combined_outputs["progress_bar"] = log_dict
        else:
            tqdm_keys = ["rouge_mean"]
            combined_outputs["progress_bar"] = {
                k: v
                for k, v in log_dict.items()
                if any([t_k in k for t_k in tqdm_keys])
            }

        return combined_outputs

    def test_epoch_end(self, outputs):
        all_dict_paths = os.listdir(self.log_path)
        d = {}

        for path in all_dict_paths:
            with open(os.path.join(self.log_path, path), "rb") as f:
                d_i = pickle.load(f)

            for k, v in d_i.items():
                d[k] = v

        with open(os.path.join(self.log_path, "results.pck"), "wb") as f:
            pickle.dump(d, f)

    def configure_optimizers(self):
        optimizer = torch.optim.Adam(
            [
                {
                    "params": self.embeddings.parameters(),
                    "lr": self.learning_rate * 0.1,
                },
                {"params": self.wl_encoder.parameters()},
                {"params": self.model.sl_encoder.parameters()},
                {
                    "params": self.model.decoder.parameters(),
                    "lr": self.learning_rate * 0.1,
                },
                {
                    "params": self.model.pretraining_decoder.parameters(),
                    "lr": self.learning_rate * 0.1,
                },
            ],
            lr=self.learning_rate,
            betas=[0, 0.999],
            weight_decay=self.weight_decay,
        )

        self.lr_scheduler = ReduceLROnPlateau(
            optimizer, mode="max", patience=10, factor=0.1, verbose=True
        )

        return optimizer

    def train_dataloader(self):
        dataset = self.splits["train"]
        return DataLoader(
            dataset,
            collate_fn=TextDataCollator(
                self.fields,
                self.reward_builder,
                subset="train",
                pad_idx=self.pad_idx,
                return_ngrams=True,
            ),
            batch_size=self.train_batch_size,
            num_workers=4,
            pin_memory=True,
            drop_last=True,
        )

    def val_dataloader(self):
        dataset = self.splits["train"]
        return DataLoader(
            dataset,
            collate_fn=TextDataCollator(
                self.fields,
                self.reward_builder,
                subset="train",
                pad_idx=self.pad_idx,
                return_ngrams=True,
            ),
            batch_size=self.test_batch_size,
            num_workers=4,
            pin_memory=True,
            drop_last=True,
        )

    def test_dataloader(self):
        dataset = self.splits["train"]
        return DataLoader(
            dataset,
            collate_fn=TextDataCollator(
                self.fields,
                self.reward_builder,
                subset="train",
                pad_idx=self.pad_idx,
                return_ngrams=True,
            ),
            batch_size=self.test_batch_size,
            num_workers=4,
            pin_memory=True,
            drop_last=True,
        )

    @staticmethod
    def from_config(dataset, reward, config):
        return LinSITExpPriors(dataset, reward, config,)


class RLSummModel(torch.nn.Module):
    def __init__(self, hidden_dim, decoder_dim, dropout):
        super().__init__()
        self.sl_encoder = torch.nn.LSTM(
            input_size=2 * hidden_dim,
            hidden_size=hidden_dim,
            num_layers=2,
            bidirectional=True,
            batch_first=True,
            dropout=dropout,
        )
        self.pretraining_decoder = torch.nn.Linear(hidden_dim * 2, 1)
        self.decoder = torch.nn.Sequential(
            torch.nn.Linear(hidden_dim * 2, decoder_dim),
            torch.nn.Dropout(dropout),
            torch.nn.ReLU(),
            torch.nn.Linear(decoder_dim, 1),
            torch.nn.Sigmoid(),
        )

    def sentence_level_encoding(self, contents):
        sent_contents, _ = self.sl_encoder(contents)

        return sent_contents

    def produce_affinities(self, sent_contents):
        affinities = self.decoder(sent_contents).squeeze(-1)

        return affinities

    def forward(self, x):
        pass
