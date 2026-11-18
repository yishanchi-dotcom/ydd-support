# 1点点 跨店支援工时系统 · 部署与维护说明

版本：1.2.6　资料库结构：v4

## 更新记录

| 版本 | 日期 | 内容 | 资料库 |
|---|---|---|---|
| 1.2.6 | 2026-11-18 | HTTPS：系统可直接提供 https（config.json 的 tls_cert / tls_key），原 http 端口自动转到 https 并提供证书验证档；`https_setup.sh` 一键为伺服器 IP 申请 Let's Encrypt 6 天短效证书并自动续期；人资首页在证书剩余不到 3 天时提示；演示版共用同一张证书 | 无变更 |
| 1.2.5 | 2026-11-16 | 演示版每次重置时自动从正式版套用高德金钥（只读）；演示版设定页不显示、也不能修改金钥 | 无变更 |
| 1.2.4 | 2026-11-16 | 发起支援新增「进阶设定」：可直接选非营运支援与项目（开会 / 大扫除 / 筹备 / 培训），去总部时隐藏；演示版横条不再遮住标题 | 无变更 |
| 1.2.3 | 2026-11-16 | 演示版：`demo_install.sh` 一键安装到 /opt/ydd-demo（端口 8081，独立资料库，每天凌晨 4 点重置示范资料）；登录页列出示范账号、画面顶部显示「演示版」 | 无变更 |
| 1.2.2 | 2026-11-16 | 修正：加载中切换页面时出现「Cannot set properties of null」红色提示；长途提示显示驾车 / 直线 / 人资指定 | 无变更 |
| 1.2.1 | 2026-11-16 | 长途改用高德驾车距离（需「Web 服务」Key；失败自动退回直线距离）；手机定位座标自动转高德座标；人资「两店距离与长途」页：查看两店距离、指定长途 / 非长途、重新取得距离 | v3 → v4 |
| 1.2.0 | 2026-11-16 | 营运 / 非营运工时拆分；法定节假日三倍薪（预置 2027 年 13 天）；夜班补贴；长途补贴（直线距离 ≥ 20 公里）；门店首次登录需填营业时间（可分平日 / 周末）与位置；超出营业时间需选特殊状况；总部（人资确认、午休 12–13 点不计）；人资「设定」页与「重新计算」；导出栏位按实际发生显示；「员工」改称「伙伴」 | v2 → v3（自动升级，旧记录视为营运、非节假日） |
| 1.1.0 | 2026-11-15 | 新增「工时调整」：已归档的记录，任一方门店可提出修改实际时间，由另一方门店确认；待确认期间不能签名；月结 Excel 增加「工时调整记录」栏 | v1 → v2（自动升级，旧资料保留） |
| 1.0.0 | 2026-11-14 | 首次上线 | v1 |

## 一、系统组成

```
ydd-support/
├─ server.py            服务主程式（Python 标准库，无需安装任何套件）
├─ db.py                资料库结构与版本升级规则
├─ migrate.py           资料库升级 / 检查 / 备份工具（可单独执行）
├─ xlsx.py              Excel 读写（导入、导出）
├─ demo_seed.py         演示版示范资料（只在 config.json "demo": true 的目录执行）
├─ demo_install.sh      在伺服器安装 / 更新演示版
├─ https_setup.sh       为伺服器 IP 申请免费 HTTPS 证书并自动续期
├─ rules.py             工时与补贴计算规则（三倍薪、夜班、长途、非营运、总部午休）
├─ static/index.html    手机网页介面
├─ config.example.json  设定档范例（复制为 config.json 后修改）
├─ start.bat / start.sh 启动脚本
└─ data/                （首次启动自动建立）
   ├─ support.db        资料库：账号、人员、支援记录、签名、操作日志
   └─ backups/          自动备份
```

- 不连接任何外部网站或 CDN，境内内网、外网都可用。
- 需求：Python 3.8 以上（Windows / Linux / macOS 皆可）。

## 二、在自己电脑上测试

1. 安装 Python 3（Windows 安装时勾选「Add Python to PATH」）。
2. 双击 `start.bat`（Windows）或执行 `./start.sh`（Mac / Linux）。
3. 电脑浏览器打开 `http://localhost:8080`。
4. 手机连同一个 Wi-Fi，打开主控台显示的「同一 Wi-Fi 的手机打开」网址（例如 `http://192.168.1.23:8080`）。
   - 若手机打不开：Windows 防火墙需允许 Python 连线（首次启动时的弹窗选「允许」）。
5. 首次打开会要求建立人资账号，之后在「门店账号」「人员清单」导入资料即可开始测试。
6. 测试完要重来：停止服务，删除 `data` 资料夹，再重新启动。

## 三、正式部署（交给 IT）

1. 把整个资料夹放到伺服器（例如 `D:\ydd-support` 或 `/opt/ydd-support`）。
2. 复制 `config.example.json` 为 `config.json`，按需修改：

| 设定 | 预设 | 说明 |
|---|---|---|
| port | 8080 | 服务端口 |
| db_path | data/support.db | 资料库位置（建议放在有备份的磁碟） |
| log_retention_days | 60 | 操作日志保留天数（约两个月），每 6 小时自动清理一次 |
| session_days | 60 | 登录状态保留天数 |
| trust_proxy | false | 若架在 Nginx 等反向代理后面，设为 true 才能记录真实 IP |
| daily_backup | true | 每日自动备份资料库到 data/backups |
| backup_keep | 30 | 每日备份保留份数 |

3. 设为开机自动启动：
   - **Linux（systemd）**：建立 `/etc/systemd/system/ydd-support.service`
     ```
     [Unit]
     Description=YDD support hours
     After=network.target
     [Service]
     WorkingDirectory=/opt/ydd-support
     ExecStart=/usr/bin/python3 server.py
     Restart=always
     [Install]
     WantedBy=multi-user.target
     ```
     然后 `systemctl enable --now ydd-support`
   - **Windows**：用「工作排程器」在开机时执行 `start.bat`，或用 NSSM 注册为服务。
4. 建议加上 HTTPS 与网域（例如 Nginx 反向代理到 8080，并设定 `trust_proxy: true`）。
   Nginx 需加上：`proxy_set_header X-Forwarded-For $remote_addr;`
5. 健康检查网址：`/healthz`

## 四、操作日志

- 记录内容：时间、账号、操作、内容、来源 IP、手机型号 / 浏览器、User-Agent。
- 记录项目：登录（含失败）、退出、发起、同意、驳回、撤回、疑义、人资处理、签名、退回签名、导出、账号与人员的新增/修改/导入。
- 手机型号：Android 通常可识别到型号（如 SM-S9180）；iPhone 因苹果限制只能识别为 iPhone 与 iOS 版本。
- 自动保留 60 天（约两个月），过期自动删除，并在日志中留下「清理日志」记录。
- 人资可在「操作日志」页按日期、账号、操作、关键字查询并导出 Excel。

## 五、程式更新与资料库升级（向下兼容规则）

**更新步骤：**
1. 停止服务。
2. 用新版档案覆盖程式档（`server.py`、`db.py`、`rules.py`、`migrate.py`、`xlsx.py`、`static/`；直接 `unzip -o` 新版压缩包即可）。**不会覆盖 `data/` 与 `config.json`**。
3. 执行 `python migrate.py`：自动备份资料库（`data/backups/*_before_vN.db`），并套用新版的资料库升级。
   - 不执行也可以：启动服务时会自动做同样的事。
4. 启动服务。

**检查版本：** `python migrate.py --status`
**手动备份：** `python migrate.py --backup`

**开发规则（每次改版都遵守）：**
- 资料库升级步骤写在 `db.py` 的 `MIGRATIONS` 末尾，只能追加，已发布的步骤不可修改或删除。
- 只做「加法」：新增资料表、新增栏位（必须有预设值）、新增索引、修正资料；不删除、不改名旧栏位。
- 升级失败会整批回滚，资料库保持原样；也可用 backups 里的备份档还原（停止服务后把备份档改名为 support.db 覆盖）。
- 若用旧版程式打开已升级的资料库，程式会拒绝启动并提示，避免写坏资料。

## 六、资料表一览

| 资料表 | 内容 |
|---|---|
| accounts | 门店 / 人资账号（编号、名称、电话、启用） |
| staff | 人员清单（门店、姓名、工号、在职） |
| requests | 支援记录（日期、时间、工时、派出/接收门店、人员、状态、疑义） |
| request_events | 每笔记录的处理历程（发起、同意、驳回、疑义、人资处理） |
| confirms | 月底店长签名确认（签名图片、确认时的工时快照） |
| store_hours | 门店营业时间（每天 + 指定星期 / 节假日） |
| holidays | 三倍薪日期（法定节假日） |
| settings | 补贴单价、门槛、准备 / 打烊分钟、总部午休、地图金钥、距离计算方式 |
| store_distances | 两店距离快取（驾车 / 直线）；门店位置或金钥改变时自动清除重算 |
| long_overrides | 人资指定两店是否长途（优先于距离判断） |
| sessions | 登录会话 |
| logs | 操作日志（IP、装置） |
| schema_migrations | 资料库版本纪录 |

## 七、注意事项

- **登录不需密码**：知道门店编号就能登录该门店。建议只在公司内网或加上 HTTPS 后使用，并定期查看操作日志中的异常 IP / 装置。之后如需恢复密码或短信验证，可依上方规则新增栏位升级，不影响旧资料。
- 微信内置浏览器可能无法直接下载 Excel，请点右上角「…」选择「在浏览器打开」后再导出。


## 演示版

与正式版分开运行：目录 `/opt/ydd-demo`、资料库 `data/demo.db`、端口 8081、服务 `ydd-demo`。

- 安装或更新（正式版更新后执行一次即可同步）：`bash /opt/ydd-support/demo_install.sh`
- 云服务器防火墙需放行 TCP 8081；网址 `http://伺服器IP:8081`
- 每天凌晨 4 点由 `/etc/cron.d/ydd-demo` 重置示范资料；手动重置：`systemctl stop ydd-demo && cd /opt/ydd-demo && python3 demo_seed.py && systemctl start ydd-demo`
- 停用演示版：`systemctl disable --now ydd-demo && rm /etc/cron.d/ydd-demo`
- `demo_seed.py` 只在 config.json 含 `"demo": true` 的目录执行，正式版执行会被拒绝
- 高德金钥：演示版 config.json 的 `demo_keys_from` 指向正式版资料库，每次重置时以只读方式复制金钥；演示版设定页不显示、不能修改金钥。正式版改了金钥，演示版隔天凌晨（或手动重置后）生效


## HTTPS（不用网域、不用备案）

用 Let's Encrypt 的 IP 证书（效期 6 天，必须自动续期）。

1. 阿里云防火墙放行 TCP 80、443
2. 伺服器执行：`bash /opt/ydd-support/https_setup.sh`（取不到 IP 时：`bash /opt/ydd-support/https_setup.sh 47.95.151.115`）
3. 脚本会：安装 snap 版 certbot（≥ 5.4）→ 以 webroot 方式申请证书（验证档放在 data/acme，由系统在 80 端口提供）→ 设定剩 3 天续期、续期后重启服务 → 在 config.json 写入 tls_cert / tls_key / https_port → 重启
4. 启用后：443 提供系统；80 只做「转到 https」与证书验证；演示版 8081 改为 https
5. 续期：certbot 的 systemd 排程每天检查两次；人资首页在证书剩余不到 3 天时显示警告。手动续期：`certbot renew`
6. 关闭 HTTPS：把 config.json 的 tls_cert 改为空字串，重启服务

注意：http 与 https 是不同网址，启用后每部手机需要重新登录一次（只要输入账号）。
