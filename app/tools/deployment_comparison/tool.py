from app.tools.deployment_utils.tool import _run

from . import service


def register(mcp):
    @mcp.tool()
    async def compare_docker_compose(before: str, after: str, limit: int = 20) -> str:
        """Compare selected declarations in two supplied Compose YAML files.
        Services match by exact name; compares images/build paths, ports,
        dependencies, environment names, health-check settings and resource names.
        No value-only secret/command changes, interpolation/include/extends/override
        resolution, execution, file/network access or deployment-safety verdict.
        Each input: 200000 chars, 10000 expanded YAML nodes, depth 50, 100 services.
        Full bounded records compared before limiting; limit 1-50 per output list,
        displayed strings 2000 chars, output 100000 chars, explicit truncation.
        """
        return await _run(service.compare_compose, before, after, limit)

    @mcp.tool()
    async def compare_kubernetes_manifests(before: str, after: str, limit: int = 20) -> str:
        """Compare selected supplied Kubernetes YAML/JSON object declarations.
        Matches exact API group/kind/declared namespace/name; duplicates ambiguous,
        generateName-only objects unmatchable. Common workloads/Services compare
        images, replicas, resource/probe/port settings and Secret/ConfigMap refs.
        Unsupported kinds metadata only; no values, cluster/default inference,
        Helm/Kustomize rendering, execution, file/network or safety verdict.
        Each input: 200000 chars, 100 documents/objects, 10000 expanded nodes,
        depth 50, 200 containers. Limit 1-50 per output list, strings 2000 chars,
        output 100000 chars; full bounded records compared, explicit truncation.
        """
        return await _run(service.compare_kubernetes, before, after, limit)

    @mcp.tool()
    async def compare_github_actions(before: str, after: str, limit: int = 20) -> str:
        """Compare selected supplied GitHub Actions YAML workflow declarations.
        Exact job IDs; triggers/filters, explicit permissions, runners, needs,
        action refs, step sequences, environment names and matrix-axis names.
        No run/with/secret values, expression/matrix/reusable-workflow resolution,
        effective permission inference, execution/file/network or safety verdict.
        Each input: 200000 chars, 10000 expanded YAML nodes, depth 50, 100 jobs,
        1000 steps. Full bounded jobs/steps compared before limit 1-50 per output
        list; strings 2000 chars, output 100000 chars, explicit truncation.
        """
        return await _run(service.compare_actions, before, after, limit)

    @mcp.tool()
    async def compare_fly_configs(before: str, after: str, limit: int = 20) -> str:
        """Compare selected supplied fly.toml declarations: app/region,
        service ports/checks, autostart/autostop, VM settings, mounts, build/deploy
        settings and environment/process key names. Values and commands omitted.
        No default/CLI/live Machine/pricing inference, execution/deployment or
        file/network access; not full config validation or a safety verdict.
        Each input: 200000 chars, 10000 nodes, depth 50, 100 entries/collection.
        Full records compared; limit 1-50 per output list, strings 2000 chars,
        output 100000 chars with explicit truncation. Names/paths may be sensitive.
        """
        return await _run(service.compare_fly, before, after, limit)
