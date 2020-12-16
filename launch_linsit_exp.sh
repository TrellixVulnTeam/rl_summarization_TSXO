#!/bin/bash

#SBATCH --account=def-adurand                                                  # Account with resources
#SBATCH --gres=gpu:t4:1                                                        # Number of GPUs
#SBATCH --cpus-per-task=8                                                      # Number of CPUs
#SBATCH --mem=80G                                                              # memory (per node)
#SBATCH --time=0-12:00                                                         # time (DD-HH:MM)
#SBATCH --mail-user=mathieu.godbout.3@ulaval.ca                                # Where to email
#SBATCH --mail-type=FAIL                                                       # Email when a job fails
#SBATCH --output=/project/def-lulam50/magod/rl_summ/slurm_outputs/%A_%a.out    # Default write output on scratch, to jobID_arrayID.out file
#SBATCH --signal=SIGUSR1@90                                                    # Killing signal 90 seconds before job end

mkdir /project/def-lulam50/magod/rl_summ/slurm_outputs/

source ~/venvs/default/bin/activate

python -um src.scripts.linsit_exp
