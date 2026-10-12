# GitHub Release 同步

工作流 `.github/workflows/sync-kernel.yml` 跟踪 `ophub/kernel` 的
`kernel_stable` Release 中最新的 `6.12.y.tar.gz`。它只在仓库默认分支运行，
支持每小时的 schedule 和手工 workflow dispatch。

## 配置

在仓库的 Actions Secrets 中配置：

- `APT_SIGNING_KEY`：用于签名 APT 索引的私钥 armored export。
- `APT_SIGNING_FINGERPRINT`：对应签名公钥的完整指纹。

私钥仅通过受保护的 Secret 导入 runner 的临时签名目录，不提交到 Git，
不进入 Release 资产。`GITHUB_TOKEN` 由 Actions 提供，用于发布 Releases。
已有客户端必须继续使用同一把签名公钥；轮换密钥需要单独安排客户端信任迁移。

当前工作流使用 `--with-m13-profile`，因此同一套通用 Image 和元包之外，还
发布一个可选的 M13 support 包。其他设备不需要安装它。新建纯通用仓库时可
移除此参数。已经发布 M13 profile 的仓库不能直接停用它：同步和发布会拒绝
这种切换，防止已安装的菜单配置指向新内核中缺失的 DTB。需要先迁移客户端，
或使用单独的仓库提供纯通用系列。改变 profile 或打包代码要使用新的 revision。

## 版本规则

工作流 revision 为 `1000 + GITHUB_RUN_NUMBER`，1–999 留给本地构建。
软件包版本为 `<kernel-version>-1+ophub.<revision>`；元包另使用 epoch `1:`。
版本化 `.deb` 的名称和内容不可覆盖，也不会自动删除旧包。

- Flat APT 地址：`https://github.com/lotusmomo/ophub-kernel-debian/releases/download/apt-6.12/`
- 不可变快照：`kernel-<release>-r<revision>`
- manifest：记录上游资产、SHA-256、recipe commit、profile、包摘要和签名指纹。

上游版本、资产 ID、更新时间或 digest 变化，以及打包 commit 或板级 DTB
变化，都会触发重新打包。同版本上游资产被替换时也会生成新的 revision。
没有输入变化时，每天刷新签名元数据；Release 索引有效期为七天。

## 发布一致性

先上传软件包，再更新索引；历史软件包摘要必须与现有签名元数据一致。
每个不可变快照先保存完整的 `metadata-generation.tar.xz`，重试时复用首次
签名的同一组字节。更换 APT 索引前保存经过认证的 `publication-journal.tar.xz`。
runner 中断后，下次同步验证 journal 和远端包摘要，再完成恢复。

GitHub Release 资产更新不是原子操作。APT 客户端若遇到短暂 hash mismatch，
应等待并重试，不能关闭认证。普通发布错误会尝试恢复上一代索引。
缺少可认证恢复信息的旧不完整快照会停止发布，必须先检查并修复。

GitHub 可能延迟 scheduled workflow，或停用长期不活跃仓库的 schedule。
需要查看 Actions 状态，而不是只依赖 cron 时间。私有仓库的 Release URL
不能直接作为匿名公共 APT 源；确认仓库可见性、签名配置和首次资产发布完成后，
再向客户端提供源地址。
