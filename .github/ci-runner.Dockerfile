# GitHub's ubuntu-24.04 runner as far as CI's jobs use it, for running them on a computer of one's own
# (.github/ci_local.py): the same system and Python (3.12, with PyYAML), Docker's command line with buildx (the jobs'
# containers go to this computer's Docker), a C++ compiler with zlib's headers, ShellCheck 0.9.0 as the runner has it,
# Helm 3.16.4 as azure/setup-helm gives it, and the usual unpackers. The jobs run as a user who is not root, as on GitHub.
FROM ubuntu:24.04
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        ca-certificates curl git python3 python3-yaml g++ make zlib1g-dev shellcheck docker.io docker-buildx \
        unzip zip xz-utils zstd file jq openssl tzdata \
    && rm -rf /var/lib/apt/lists/*
# Helm at the version the workflow's setup step names (.github/workflows/ci.yml, azure/setup-helm).
RUN curl -fsSL https://get.helm.sh/helm-v3.16.4-linux-amd64.tar.gz | tar -xzf - -C /usr/local/bin --strip-components 1 linux-amd64/helm
# A clone anyone may read (the job's user is whoever runs ci_local.py, or 1001 as on GitHub when that is root).
RUN git config --system --add safe.directory '*'
