import numpy as np


class UCBProcess:
    def __init__(self, ucb_sampling, c_puct):
        self.ucb_sampling = ucb_sampling
        self.c_puct = c_puct

    def __call__(self, scorer, priors=None):
        n_sents = min(scorer.n_sents, 50)

        if self.ucb_sampling == "fix":
            n_samples = 100
        elif self.ucb_sampling == "linear":
            n_samples = 2 * n_sents + 50
        else:
            raise NotImplementedError(
                f"{self.ucb_sampling} is not a valid UCB sampling method."
            )

        return ucb(scorer, self.c_puct, n_samples, n_sents, priors)


def ucb(scorer, c_puct, n_samples, n_sents, priors=None):
    if not priors:
        priors = np.ones((n_sents,)) / n_sents

    n_visits = np.zeros(n_sents, dtype=int)
    q_vals = np.zeros(n_sents, dtype=np.float32)

    for n in range(1, n_samples + 1):
        ucb = q_vals + c_puct * priors * np.sqrt(2 * np.log(n) / n_visits)
        ucb = np.nan_to_num(ucb, nan=np.inf)
        threshold = np.partition(ucb, -3)[-3]
        elligible_idxs = np.argwhere(ucb >= threshold)[:, 0]
        sampled_idxs = np.random.choice(elligible_idxs, 3, replace=False)
        summ_score = scorer(tuple(sampled_idxs))
        q_vals[sampled_idxs] = (
            summ_score + q_vals[sampled_idxs] * n_visits[sampled_idxs]
        ) / (n_visits[sampled_idxs] + 1)
        n_visits[sampled_idxs] += 1

    max_score = scorer.scores.max()
    threshold = np.partition(q_vals, -3)[-3]
    elligible_idxs = np.argwhere(q_vals >= threshold)[:, 0]
    best_idxs = np.random.choice(elligible_idxs, 3, replace=False)
    best_score = scorer(tuple(best_idxs))
    ucb_delta = max_score - best_score

    returned_q_vals = np.zeros(50, dtype=np.float32)
    returned_q_vals[:n_sents] = q_vals

    return (returned_q_vals, ucb_delta)
