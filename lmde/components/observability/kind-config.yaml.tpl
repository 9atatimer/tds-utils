kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
- role: control-plane
  extraPortMappings:
  - containerPort: 3000
    hostPort: 3000
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
