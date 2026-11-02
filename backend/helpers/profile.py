import yaml

from core import constants


def load_profile():
    with open(constants.PROFILE_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)
