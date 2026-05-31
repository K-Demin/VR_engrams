# -*- coding: utf-8 -*-
"""
Created on Fri Feb 27 16:14:01 2026

@author: JoshB
"""

import nidaqmx
import time
import random
import csv
import os
import argparse
import yaml
from datetime import datetime


# -------------------------
# Utilities
# -------------------------

def load_yaml(path):
    with open(path, 'r') as f:
        return yaml.safe_load(f)


def save_yaml(data, path):
    with open(path, 'w') as f:
        yaml.dump(data, f)


def merge_config(yaml_config, cli_args):
    config = yaml_config.copy()

    # Override YAML with CLI if provided
    if cli_args.trials is not None:
        config["n_trials"] = cli_args.trials

    if cli_args.puff_ms is not None:
        config["puff_ms"] = cli_args.puff_ms

    if cli_args.base_path is not None:
        config["base_path"] = cli_args.base_path

    config["animal_id"] = cli_args.animal

    return config


# -------------------------
# Localiser Class
# -------------------------

class LocaliserTask:

    def __init__(self, config):

        self.config = config
        self.session_start_time = None

        self.setup_session_folder()
        self.setup_logging()

    def setup_session_folder(self):
        date_str = datetime.now().strftime("%Y-%m-%d")
        time_str = datetime.now().strftime("%H-%M-%S")

        self.session_path = os.path.join(
            self.config["base_path"],
            self.config["animal_id"],
            date_str,
            f"localiser_{time_str}"
        )

        os.makedirs(self.session_path, exist_ok=True)

        # Save resolved config for reproducibility
        save_yaml(self.config, os.path.join(self.session_path, "config_used.yaml"))

    def setup_logging(self):
        log_path = os.path.join(self.session_path, "behaviour_log.csv")
        self.log_file = open(log_path, mode='w', newline='')
        self.csv_writer = csv.writer(self.log_file)
        self.csv_writer.writerow(["timestamp_sec", "event", "trial"])

    def log_event(self, event, trial):
        timestamp = time.time() - self.session_start_time
        self.csv_writer.writerow([timestamp, event, trial])
        self.log_file.flush()

    def deliver_air_puff(self):
        with nidaqmx.Task() as task:
            task.do_channels.add_do_chan(self.config["airpuff_line"])

            task.write(False)
            time.sleep(0.01)

            task.write(True)
            time.sleep(self.config["puff_ms"] / 1000)

            task.write(False)

    def run(self):

        print("Starting localiser...")
        self.session_start_time = time.time()

        for trial in range(self.config["n_trials"]):

            iti = random.uniform(
                self.config["iti_min"],
                self.config["iti_max"]
            )
            time.sleep(iti)

            self.log_event("trial_start", trial+1)

            self.deliver_air_puff()

            self.log_event("puff", trial+1)

        self.log_event("session_end", -1)
        self.log_file.close()

        print("Session complete.")


# -------------------------
# CLI
# -------------------------

def parse_args():
    parser = argparse.ArgumentParser(description="Somatosensory Localiser Task")

    parser.add_argument("--animal", required=True, help="Animal ID")
    parser.add_argument("--config", default="configs/localiser_default.yaml")
    parser.add_argument("--trials", type=int)
    parser.add_argument("--puff_ms", type=int)
    parser.add_argument("--base_path")

    return parser.parse_args()


# -------------------------
# Main
# -------------------------

def main():

    args = parse_args()

    yaml_config = load_yaml(args.config)
    final_config = merge_config(yaml_config, args)

    task = LocaliserTask(final_config)
    task.run()


if __name__ == "__main__":
    main()