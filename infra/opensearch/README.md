# OpenSearch

OpenSearch runs as a single node with the security plugin disabled for the local lab and a heap set by `OPENSEARCH_JAVA_OPTS` (default 1 GB).
The image bundles the k-NN and neural-search plugins used for `knn_vector` fields and hybrid search pipelines; no custom settings are mounted.

## Host memory map limit

On Linux hosts and WSL2, OpenSearch fails its bootstrap checks unless `vm.max_map_count` is at least 262144.

```bash
sudo sysctl -w vm.max_map_count=262144
```

Persist it on Linux with a file such as `/etc/sysctl.d/99-opensearch.conf` containing `vm.max_map_count=262144`.
With Docker Desktop on WSL2, add `kernelCommandLine = "sysctl.vm.max_map_count=262144"` under `[wsl2]` in `%UserProfile%\.wslconfig`, then run `wsl --shutdown`.
