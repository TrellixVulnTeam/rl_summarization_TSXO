#!/bin/bash

#SBATCH --account=def-adurand                                                  # Account with resources
#SBATCH --cpus-per-task=16                                                     # Number of CPUs
#SBATCH --mem=50G                                                              # memory (per node)
#SBATCH --time=0-03:00                                                         # time (DD-HH:MM)
#SBATCH --mail-user=mathieu.godbout.3@ulaval.ca                                # Where to email
#SBATCH --mail-type=FAIL                                                       # Email when a job fails
#SBATCH --output=/project/def-adurand/magod/rl_summ/slurm_outputs/%A_%a.out    # Default write output on scratch, to jobID_arrayID.out file
#SBATCH --signal=SIGUSR1@90                                                    # Killing signal 90 seconds before job end

mkdir /project/def-adurand/magod/rl_summ/slurm_outputs/

source ~/venvs/default/bin/activate

python -um src.scripts.mcts_exp

# SIT = Self improving Target -> chap 3 -> cucb
# LinSIT => chap 4
# MCS -> chap2 -> BanditSum