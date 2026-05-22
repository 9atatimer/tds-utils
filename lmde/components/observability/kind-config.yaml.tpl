# kind cluster config for the LMDE observability stack.
# @DATA_DIR@ is substituted with the host persistence path by setup.sh.
#
# Host ingress: containerPort 80 is where the ingress-nginx controller
# listens on the node; it is published to host 127.0.0.1:32100 (the
# observability cluster's slot in the 3210X ingress-port convention).
# Caddy reverse-proxies *.lmde.localhost to that port.
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
- role: control-plane
  kubeadmConfigPatches:
  # Label the node so the ingress-nginx kind manifest will schedule
  # its controller here (nodeSelector: ingress-ready=true).
  - |
    kind: InitConfiguration
    nodeRegistration:
      kubeletExtraArgs:
        node-labels: "ingress-ready=true"
  extraPortMappings:
  - containerPort: 80
    hostPort: 32100
    listenAddress: "127.0.0.1"
    protocol: TCP
  - containerPort: 4317
    hostPort: 4317
    listenAddress: "127.0.0.1"
    protocol: TCP
  - containerPort: 4318
    hostPort: 4318
    listenAddress: "127.0.0.1"
    protocol: TCP
  extraMounts:
  - hostPath: @DATA_DIR@
    containerPath: /mnt/data
