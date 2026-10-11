# ADR 0011：采用 Assisted ACK

V2A 明确要求原生人工导入，故不做浏览器注入或修改 cursor。Web 下载/复制官方 ACK，ReceiptSource 自动发现后调用官方 ack consume。没有改变 Review、Receipt、single pending 或幂等语义。TEST Receipt 只属于验收输入，不是原生 V2A 执行证据。
