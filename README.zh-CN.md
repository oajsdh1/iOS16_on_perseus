# iOS 16 on Mi MIX 3 (perseus)

将 [JaneAwA/iOS16_on_mix2s](https://github.com/JaneAwA/iOS16_on_mix2s)（polaris /
Mi MIX 2S，基线为 [dipa-studio/ios-sweet](https://github.com/dipa-studio/ios-sweet)）
的补丁集适配到同为骁龙 845 的小米 MIX 3（perseus）。

引导链与上游一致：**官方 ABL → `fastboot boot`（内存引导，不改任何分区，重启即回
安卓）→ boot shim → XNU (PERSEUS 机器配置) → HFS+ 根卷**。XNU 只能在 macOS 工具链
下编译，用 GitHub Actions `macos-14` runner 构建；UEFI/shim 在 Linux 上原生编译。

## 相对 polaris 的差异（全部板级数据都在 ADT/shim，内核无地址）

| 项 | polaris (MIX 2S) | perseus (MIX 3) | 状态 |
|---|---|---|---|
| 帧缓冲 | 0x9d400000, 1080×2160 | 0x9d400000, **1080×2340** | 地址已在 MIX 3 真机点亮（hackios xnuloader） |
| cont_splash 大小 | 0x2400000 | 0x2400000（沿用） | 待 stock DTB 解码确认 |
| GIC / UFS / 时钟 / 8 核 | 0x17a00000/0x17a60000, 0x1d84000, 19.2MHz, Kryo 385 | 相同 | 同 SoC |
| boot 头 | v2 + dtb | **v1、无 dtb 字段** | perseus ABL 是 2018 Pie 年代；hackios 镜像同形状已真机启动 |
| 机器配置 | POLARIS | **PERSEUS**（= POLARIS 同款 SWEET 变体） | 一套补丁同时支持两个配置 |

## 仓库内容

- `patches/upstream-perseus.diff` — 套到 dipa-studio/ios-sweet main（基线
  45263bee，2026-10-23）上的全部改动：mkadt/mkpayload 三机器化、shim 帧缓冲常量、
  v1 打包、workflow 默认 PERSEUS、xnu 0099–0104 嵌套补丁（POLARIS+PERSEUS）。
- `xnu/patches/` — 上面嵌套补丁的分发副本（CI 会从 fork 的同名目录收集）。
- `ci/xnu-perseus.yml` — workflow 正本（fork 应用 diff 后得到同名文件）。
- `tools/mkbootimg.py` — vendored AOSP 脚本（Ubuntu 24.04 的 apt mkbootimg 缺 gki
  模块，build.sh 默认用它，可用 `MKBOOTIMG=` 覆盖）。
- `hardware/perseus.txt` — 硬件参数与出处（[V] 真机验证 / [P] polaris 同 SoC / [A] 假定）。
- `out/perseus-shim-boot.img` — 已构建的 shim 诊断镜像（空 ramdisk → 屏幕探针输出）。

## 第一次上机（无需内核、无需 macOS）

```bash
adb reboot bootloader
fastboot boot out/perseus-shim-boot.img
```

预期：屏幕出现红底白字控制台，依次输出 loader（无 payload 路径）、UFS 探针
（读 0x1d84000）、MMU/页表、PSCI/SMCCC 版本、GICv3 vtimer 中断与 SGI 测试，
约 3 分钟后自动重启回安卓。任何异常都会有 panic 屏与 stage 标签。

## 构建 PERSEUS 内核（需要 GitHub）

```bash
git clone https://github.com/<you>/ios-sweet.git
./apply_to_upstream.sh /path/to/ios-sweet main
cd /path/to/ios-sweet && git checkout -b perseus-port && git commit -am "perseus port" && git push -u origin perseus-port
./ci/trigger_build.py --repo <you>/ios-sweet --config PERSEUS --wait
```

（`apply_to_upstream.sh` 会把 workflow 一并带进 fork；Actions 里
`machine_config` 选 `PERSEUS`，也可选 `POLARIS` 交叉验证。）

## 后续路线（按 JaneAwA 的里程碑）

1. shim 探针真机确认（本镜像）。
2. XNU payload：`tools/mkpayload.py KERNEL out/perseus.adt payload.bin` →
   `shim/build.sh payload.bin` → fastboot boot。⚠️ 此阶段依赖 ABL 把 initrd 地址
   写进它递给 shim 的 DTB（`/chosen linux,initrd-*`）；v1 镜像无 dtb 字段，perseus
   ABL 的具体行为待真机确认（屏上会直接打出 DTB magic 与结果）。
3. iPhone X (iPhone10,3) iOS 16.7.16 IPSW 用户空间 + macOS `newfs_hfs` 根卷
   （见 `tools/mkiosroot-macos.sh`）。
4. stock perseus DTB 解码（`ci/decode_dtb.py --match perseus`）：确认 cont_splash
   大小、触摸 IC（polaris 为 Synaptics DSX，MIX 3 待查）、8GB 内存映射。

## 状态

- ✅ **shim 真机验证通过（2026-10-25，MIX 3 8GB / MIUI 12.5.1 Android 10）**：
  红底控制台点亮（0x9d400000 @1080×2340）、ABL 把 initrd 地址写进 `/chosen`
  （payload 路径可用）、UFS 探针全绿（UFSHCI 2.1，TUR/READ rc=0，读出真实
  GPT 分区表 persist/logdump/cust/recovery/cache/userdata，ext4）。
- ✅ 补丁集全部生成并在合成树上验证 `git apply` 链（0099→0102、0101→0104）
- ✅ mkadt 生成 perseus/polaris ADT（`dtb/perseus.dtb` 为从 hackios boot.img
  剥出的官方 "Perseus MP v2.1" 设备树，运行时 DTB 目录已交叉证实
  cont_splash_region@9d400000）
- 🔧 XNU CI 构建、payload 引导、用户空间

## 上机经验（perseus ABL 的坑）

1. **ABL 只在内核字段带 DTB 时才跳转**：必须是 `gzip(Image)` 后**追加**
   `perseus.dtb`（MIUI 惯例）。缺 DTB 时 `fastboot boot` 照样返回 OKAY，但
   ABL 静默放弃——黑屏、USB 死、无任何输出。
2. ramdisk 用 5 字节 stub 即可；ABL 会把 initrd 实际加载地址
   （本次为 0x055FF000）写进它递给 shim 的 DTB 的 `/chosen`。
3. usbipd 持久绑定会抢 fastboot 设备：先 `pkill usbip-auto-attach`（WSL 侧）
   再 `usbipd detach`。
