#!/bin/bash

#SBATCH --account=def-adurand                                                  # Account with resources
#SBATCH --gres=gpu:k80:1                                                       # Number of GPUs
#SBATCH --cpus-per-task=24                                                     # Number of CPUs
#SBATCH --mem=50G                                                              # memory (per node)
#SBATCH --time=0-24:00                                                         # time (DD-HH:MM)
#SBATCH --mail-user=mathieu.godbout.3@ulaval.ca                                # Where to email
#SBATCH --mail-type=FAIL                                                       # Email when a job fails
#SBATCH --output=/project/def-lulam50/magod/rl_summ/slurm_outputs/%A.out       # Default write output on scratch, to jobID_arrayID.out file
#SBATCH --signal=SIGUSR1@90                                                    # Killing signal 90 seconds before job end

mkdir /project/def-lulam50/magod/rl_summ/slurm_outputs/

source ~/venvs/default/bin/activate
cd ~/git/rl_summarization

python -um src.scripts.ngrams_calc