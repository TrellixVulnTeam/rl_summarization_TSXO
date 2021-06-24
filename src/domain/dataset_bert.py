import time
import torch

from os import listdir, getcwd
from os.path import isfile, join
from torch._C import dtype
from torch.utils.data import Dataset
from datasets import load_dataset
from transformers import BertTokenizerFast
from torchtext.data import Dataset as torchtextDataset, Example, Field, RawField
from nltk.tokenize import sent_tokenize, word_tokenize

SEN_PER_DOC = 50 # SEN_PER_DOC > 50 will raise an error because of RougeRewardScorer default max n_sents =50
MAX_LEN_SENTENCE = 80
MIN_LEN_SENTENCE = 6
MAX_NB_TOKENS_PER_DOCUMENT = 512
PAD = 0

bert_cache_dir = join(getcwd(), "bert_cache/tokenizer_save_pretrained")


class CnnDailyMailDatasetBert:
    def __init__(self, config):
        self.loaded_data = self._load_dataset(
            join(config.data_path, "finished_files", "train"),
            join(config.data_path, "finished_files", "test"),
            join(config.data_path, "finished_files", "val"),
        )
        self.config = config
        self.dataset = self.tokenized_dataset(self.loaded_data)

    def _load_dataset(self, train_dir, test_dir, val_dir, cache_dir="./cache_dir"):
        """Utility method use to load the data

        Args:
            train_dir (str): path to train directory containing files (.json) for training
            test_dir (str): path to test directory containing files (.json) for testing
            val_dir (str): path to train directory containing files (.json) for validation
            cache_dir (str): path to cache directory used by `datasets.load_dataset` 
        
        Returns:
            DatasetDict: return the dataset loaded from train_dir, test_dir and val_dir
        """

        train_files = [
            join(train_dir, f) for f in listdir(train_dir) if isfile(join(train_dir, f))
        ]
        test_files = [
            join(test_dir, f) for f in listdir(test_dir) if isfile(join(test_dir, f))
        ]
        val_files = [
            join(val_dir, f) for f in listdir(val_dir) if isfile(join(val_dir, f))
        ]

        return load_dataset(
            "json",
            data_files={"train": train_files, "test": test_files, "val": val_files},
            cache_dir=cache_dir,
        )

    def encode_document(self, document, tokenizer):
        """Utility method used to preprocess and tokenize the data
        
        Args:
            document (list): list of sentences to preprocess and tokenize
            tokenizer (BertTokenizerFast): object method used to preprocess and tokenize 

        Return:
            dict: dictionary with keys `input_ids`, `token_type_ids` and `attention_mask`
        """

        # concat sentences into document
        result_ = {
            "token_ids": [],
            "token_type_ids": [],
            "mark": [],
            "segs": [],
            "clss": [0],
            "mark_clss": [True],
            "sentence_gap": [],
        }
        current_sentence = 0
        for seg, sentence in enumerate(document[:SEN_PER_DOC]):
            # words_tokenized = word_tokenize(sentence)
            # if len(words_tokenized)>512:
            #     sentences_tokenized = sent_tokenize(sentence)
            #     ids, types, mark =[],[],[]
            #     for i, sentence_ in enumerate(sentences_tokenized):
            #         output = tokenizer(sentence_,
            #                         add_special_tokens=True,
            #                         return_tensors='pt')
            #         ids_, types_, mark_ = output['input_ids'][0], output['token_type_ids'][0], output['attention_mask'][0]
            #         if i<len(sentences_tokenized)-1:
            #             ids_=ids_[:-1]
            #             types_=types_[:-1]
            #             mark_=mark_[:-1]
            #         if i>0:
            #             ids_=ids_[1:]
            #             types_=types_[1:]
            #             mark_=mark_[1:]
            #         ids.append(ids_)
            #         types.append(types_)
            #         mark.append(mark_)

            #     ids = torch.cat(ids)
            #     types = torch.cat(types)
            #     mark = torch.cat(mark)

            # else:
            output = tokenizer(
                sentence,
                add_special_tokens=True,
                max_length=MAX_LEN_SENTENCE,
                truncation=True,
                return_tensors="pt",
            )
            ids, types, mark = (
                output["input_ids"][0],
                output["token_type_ids"][0],
                output["attention_mask"][0],
            )
            if len(ids) < MIN_LEN_SENTENCE + 2:
                current_sentence += 1
                continue
            if len(result_["token_ids"]) + len(ids.tolist()) > MAX_NB_TOKENS_PER_DOCUMENT:
                break
            result_["token_ids"].extend(ids.tolist())
            result_["token_type_ids"].extend(types.tolist())
            result_["mark"].extend(mark.tolist())
            result_["segs"].extend([seg % 2] * len(ids))
            result_["clss"].append(len(result_["segs"]))
            result_["mark_clss"].append(True)
            result_["sentence_gap"].append(current_sentence)

        result_["clss"].pop()
        result_["mark_clss"].pop()

        # padding
        pad_ = MAX_NB_TOKENS_PER_DOCUMENT - len(result_["token_ids"])
        result_["token_ids"].extend([PAD] * pad_)
        result_["token_type_ids"].extend([result_["token_type_ids"][-1]] * pad_)
        result_["mark"].extend([0] * pad_)
        result_["segs"].extend([1 - (seg % 2)] * pad_)
        return result_

    def get_values(self, set_, part_, dataset, tokenizer):
        """Utility method used inside `tokenized_dataset`
        
        Args:
            set_ (str): directory containing json files. Possible choices: 'train', 'test' or 'val'
            part_ (str): Once we've choosen `set_`, select the type of document, i.e.
            'article' or 'abstract'
            dataset (DatasetDict): dataset that will be tokenized (train, test, validation)
            tokenizer (BertTokenizerFast): object method used to preprocess and tokenize 
        
        Returns:
            list: return a list of tokenized documents 
        """
        return [
            self.encode_document(document, tokenizer)
            for document in dataset[set_][part_]
        ]

    def tokenized_dataset(self, dataset):
        """ Method that tokenizes each document in the train, test and validation dataset

        Args:
            dataset (DatasetDict): dataset that will be tokenized (train, test, validation)
        
        Returns:
            dict: dataset once tokenized
        """
        if self.config.bert_cache:  # Used if there's no internet connection
            bert_cache_dir = join(getcwd(), "bert_cache/tokenizer_save_pretrained")
            tokenizer = BertTokenizerFast.from_pretrained(
                bert_cache_dir, local_files_only=True
            )
        else:
            tokenizer = BertTokenizerFast.from_pretrained("bert-base-uncased")

        print("\n" + "=" * 10, "Start Tokenizing", "=" * 10)
        start = time.process_time()
        train_articles = self.get_values("train", "article", dataset, tokenizer)
        test_articles = self.get_values("test", "article", dataset, tokenizer)
        val_articles = self.get_values("val", "article", dataset, tokenizer)
        train_abstracts = self.get_values("train", "abstract", dataset, tokenizer)
        test_abstracts = self.get_values("test", "abstract", dataset, tokenizer)
        val_abstracts = self.get_values("val", "abstract", dataset, tokenizer)
        print("Time:", time.process_time() - start)
        print("=" * 10, "End Tokenizing", "=" * 10 + "\n")

        return {
            "train": (
                dataset["train"]["id"],
                train_articles,
                train_abstracts,
                dataset["train"]["article"],
                dataset["train"]["abstract"],
            ),
            "test": (
                dataset["train"]["id"],
                test_articles,
                test_abstracts,
                dataset["test"]["article"],
                dataset["test"]["abstract"],
            ),
            "val": (
                dataset["val"]["id"],
                val_articles,
                val_abstracts,
                dataset["val"]["article"],
                dataset["val"]["abstract"],
            ),
        }


class IdField(Field):
    """Field Objects for processing when loading data"""

    def preprocess(self, x):
        return x

    def process(self, batch, device=None):
        return batch


class DataField(Field):
    """Field Objects for processing when loading data"""

    def preprocess(self, x):
        return x

    def process(self, batch, device=None):
        """stack examples into a tensor."""

        assert len(batch) > 0

        result = {}
        for field_ in batch[0]:
            result[field_] = []

        for example in batch:
            for field_, data_ in example.items():
                result[field_].append(data_)

        for field_ in batch[0]:
            try:
                if field_ == "sentence_gap":
                    continue
                # stack to tensor for: token_ids, token_type_ids, mark, segs
                result[field_] = torch.Tensor(result[field_]).long()
                if field_ in ["mark", "mark_clss"]:
                    result[field_] = result[field_].bool()
            except Exception as e:
                result[field_] = result[field_]

        return result


class TextDatasetBert(Dataset):
    def __init__(self, dataset):
        self.examples = [
            self.__process_example(x, dataset.fields) for x in dataset.examples
        ]

    def __process_example(self, x, fields):
        return {name: getattr(x, name) for name, f in fields.items()}

    def subset(self, n):
        self.examples = self.examples[:n]

    def __getitem__(self, i):
        return self.examples[i]

    def __len__(self):
        return len(self.examples)

    def __iter__(self):
        for x in self.examples:
            yield x


class DatasetBertWrapper(CnnDailyMailDatasetBert):
    """ Wrapper used to reformat the data generated by CnnDailyMailDatasetBert """

    def __init__(self, config):
        super().__init__(config)
        self.fields = [
            ("id", IdField()),
            ("content", DataField()),
            ("abstract", DataField()),
            ("raw_content", RawField()),
            ("raw_abstract", RawField(is_target=True)),
        ]
        self.subsets = self.gen_subsets()
        self.pad_idx = 0

    def gen_subsets(self):
        """Method used to reformat the data genrated by CnnDailMailDatasetBert"""
        subsets = {}
        for subset_, document_tuples in self.dataset.items():
            examples = []
            for properties in zip(
                document_tuples[0],
                document_tuples[1],
                document_tuples[2],
                document_tuples[3],
                document_tuples[4],
            ):
                examples.append(Example.fromlist(properties, self.fields))
            subsets[subset_] = torchtextDataset(examples, self.fields)
        return subsets

    def get_splits(self):
        """Method used to build the dataloader for train, test and validation"""
        return {
            name: TextDatasetBert(dataset) for name, dataset in self.subsets.items()
        }

    @staticmethod
    def from_config(config):
        """Method used to create object on the fly (Factory Design Pattern)
        Args:
            config: configuration to fill different parameters and hyperparameters 
        """
        return DatasetBertWrapper(config)
