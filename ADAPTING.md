# 新增型号 / Adding a model

1. 为可购买且已实际测试的型号确定稳定 ID（小写字母、数字、连字符，最多63字符）。记录厂商、产品ID、实际商品名称及证据；不要把未测设备标为支持。
2. 在 `models/<id>/` 放置 v2 manifest、layout、inputs、单帧正面 PNG 和可选品牌 PNG。manifest 的 version 是格式版本，release 是独立三段数字发布版本。所有可见文字至少含 en，中英型号同时填写 zh。保留独立 `metadata.json` 中英名称、概要、步骤和限制。
3. 记录素材来源。正面 PNG <=16MiB、尺寸1…4096；品牌 PNG <=4MiB、宽高各不超过2048；JSON各<=256KiB。visible为像素矩形；热区相对完整PNG的0…1坐标，中心锚定，原点左上。ellipse/rectangle/sector，其中扇区angle从正右顺时针，innerRatio为0≤r<1。
4. 捕获每个键按下、松开、持续按住及端点断开的HID事件。collectionPage/collectionUsage/page/usage须正确；可选report、value、acceptsArray遵循v1。一个信号不能指向多个键；不要把用户动作偏好固化为输入映射。
5. doublePress/longPress只声明动作槽能力，不能让 `<id>-double` 或 `<id>-long` 与其他键ID冲突。硬件说明锚点必须引用manifest.capabilities。
6. 运行校验与单元测试，打包并解压。使用应用现有读取器验证；新型号在应用导入并用成对硬件验证。用同来源、更高 release 验证更新；跨来源覆盖及设备冲突必须拒绝。
7. 填写实体测试记录，更新中英说明和SOURCE；显式导出订阅源与官网快照；正式应用不内置真实型号。

英文规则 / English: use stable IDs; provide actual hardware evidence, v2 resources, localized copy, explicit defaults/behavior and bilingual metadata and source provenance. Capture press/release/hold/removal, validate cross-file references, test ZIP round trips and the app reader, then record physical-device checks before declaring support. Use explicit sync/export targets. No user configuration or automatic update logic belongs in an adapter.

## 展示约定 / Presentation contract

`layout.keys[].annotationSide` 和 `layout.anchors[].annotationSide` 可选，值为 `leading`（左侧）或 `trailing`（右侧）。省略或 null 时，应用按投影后的锚点位置自动选择侧边；位于中心线的锚点默认左侧。型号特有的标签方向必须在型号包声明，不得在 app 按型号 ID 或按键 ID 分支。

`manifest.capabilities[].status` 是可选的非空状态文案（v2 使用 `{en,zh}`）。省略或 null 时仅显示“硬件具备”，不根据 `usb-c` 等能力 ID 推断是否已接入。

annotationSide 为 v1 的可选扩展；status 在 v1 中为字符串，在 v2 中为本地化对象。旧 v1 包仍可由新 app 导入；v2 包需要支持 v2 的 app。app 统一负责坐标投影、热区、引线避让、选择和反馈；型号包负责图像、几何和标注意图。型号更新通过资源库显式安装，不要求重建 app；同来源更高 release 才能更新，不能覆盖用户配置。

PNG 必须交付干净的透明轮廓。原始画布、机身位置、比例和按键热区在清理中不得改变；禁止在 app 增加按型号裁切、蒙版或偏移补丁。作者可在 `artwork/<id>/` 保存原图和可复现处理配方，只有完成品进入 `models/<id>/` 与分发包。

Optional v1 fields: `annotationSide` (`leading`/`trailing`, otherwise position-based) on keys and capability anchors; `status` (non-empty text, otherwise neutral hardware-presence text) on capabilities. Consumers render these uniformly without model or capability identity checks. Clean source alpha before distribution; preserve canvas, pixel registration, and hotspot geometry.

完整字段、默认动作 Codable 结构、发布版本和订阅导出规则见 [PROTOCOL.md](PROTOCOL.md)。 / See [PROTOCOL.md](PROTOCOL.md) for the complete package/source schema.
