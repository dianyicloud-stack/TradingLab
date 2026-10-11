# ADR 0009：可替换的 Live / Decision Bridge

选择 Protocol + JSON DTO；当前 FileWorkspaceBridge 和隔离 Legacy CLI Worker，未来 HttpLiveBridge/RemoteDecisionService 通过组合根替换。路径仅由配置层和 Adapter 持有。原 1.1/1.0 身份不兼容时 fail closed，不改 ID 或冻结 Schema。Linux/微信仅接口准备，不开放公网或宣称已部署。
