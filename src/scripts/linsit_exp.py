from src.domain.utils import configure_logging, set_random_seed
from src.factories.dataset import DatasetFactory
from src.factories.model import ModelFactory
from src.factories.reward import RewardFactory

import yaml
import logging
from test_tube import HyperOptArgumentParser


def main(_config, cluster=None):
    configure_logging()
    set_random_seed(_config.seed)

    logging.info("Beginning LinSIT exp script with following config :")
    logging.info(_config)

    dataset = DatasetFactory.get_dataset(_config)
    reward = RewardFactory.get_reward(_config)
    model = ModelFactory.get_model(dataset, reward, _config)

    model.process_all()

    logging.info("Done")


if __name__ == "__main__":
    base_configs = yaml.load(open("./configs/linsit_exp.yaml"), Loader=yaml.FullLoader)
    argument_parser = HyperOptArgumentParser()
    for config, value in base_configs.items():
        if type(value) is bool:
            # Hack as per https://stackoverflow.com/a/46951029
            argument_parser.add_argument(
                "--{}".format(config),
                type=lambda x: (str(x).lower() in ["true", "1", "yes"]),
                default=value,
            )
        else:
            argument_parser.add_argument(
                "--{}".format(config), type=type(value), default=value
            )
    options = argument_parser.parse_args()
    main(options)
