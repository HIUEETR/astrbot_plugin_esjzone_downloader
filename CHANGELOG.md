# Changelog

所有重要更改都将记录在此文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，
并且本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

---

## [Unreleased]

### 新增 ✨
- 性能监控模块 (`PerformanceMonitor`)
  - 下载速度统计
  - 章节和图片成功率统计
  - 实时性能报告生成

### 改进 🚀
- 图片下载优化
  - 实现非阻塞图片下载
  - 图片下载失败不影响主流程
- 大书籍处理优化
  - 自动检测大书籍（>500章）
  - 分批下载机制
  - 批次合并逻辑

---

## [1.2.0] - 2026-06-07

### 新增 ✨
- 异步下载管理器 (`AsyncDownloadManager`)
  - 基于 asyncio 的高效并发下载
  - 章节和图片分离队列
  - 智能任务调度和负载均衡
- 收藏缓存管理器 (`FavoritesManager`)
  - 本地 JSON 缓存机制
  - 会话内去重更新
  - 异步并发获取多页
- 工具函数库 (`utils.py`)
  - 文件名清理 `sanitize_filename`
  - 文本处理和格式化工具

### 改进 🚀
- 监控系统错误处理增强
  - 单点失败不影响其他监控
  - 更详细的错误日志
- 下载性能优化
  - 从线程池转换为异步协程
  - 降低内存占用
  - 更高的并发效率

### 修复 🐛
- 修复 Pillow 依赖版本冲突（移除 `<11` 限制，兼容 AstrBot 核心的 12.1.1）

### 文档 📚
- 新增 `MIGRATION_SUMMARY.md` - 迁移工作总结
- 新增 `README_v1.2.md` - 使用说明
- 更新 `IMPROVEMENT_PLAN.md` - 标记已完成任务

---

## [1.1.0] - 2026-06-07

### 新增 ✨
- 核心模块迁移到 AstrBot 插件架构
- 异步下载管理器基础实现
- 收藏管理器基础实现
- Cookie 多用户隔离管理

### 改进 🚀
- 依赖库统一和清理
  - 移除 CLI 工具依赖（questionary, rich, tqdm, colorama, wcwidth）
  - 移除配置文件依赖（pyyaml, ruamel.yaml）
  - 保留核心依赖（beautifulsoup4, httpx, pillow）

### 变更 ⚙️
- 日志系统适配为 AstrBot 的 logger API
- 配置系统适配为 AstrBot 的配置机制

---

## [1.0.0] - 2026-04-30

### 新增 ✨
- 基础下载功能（EPUB/TXT）
- 用户登录/登出管理
- 书籍信息查询（`/esj info`）
- 收藏列表获取（`/esj fav`）
- 更新状态检查（`/esj check`）
- 分章节下载（指定起始/结束章节）
- 配置管理（`/esj cfg`）
- 更新监控系统（`/esj m add/list/rm/check`）
- 多用户支持
- Cookie 管理
- 图片下载支持
- 文件命名模式配置
- 下载限制配置（章节数、图片大小等）

### 命令 🎮
- `/esj help` - 查看帮助
- `/esj info <URL>` - 查看书籍信息
- `/esj download <URL> [格式] [起始] [结束]` - 下载书籍
- `/esj login <邮箱> <密码>` - 登录账号
- `/esj logout` - 退出登录
- `/esj fav [排序] [页码]` - 查看收藏
- `/esj check <URL>` - 检查更新
- `/esj m add <URL>` - 添加监控
- `/esj m list` - 查看监控列表
- `/esj m rm <URL|all>` - 移除监控
- `/esj m check` - 立即检查更新
- `/esj cfg [配置项] [值]` - 配置管理

---

## 版本说明

### 版本号格式
- **主版本号**: 不兼容的 API 修改
- **次版本号**: 向下兼容的功能新增
- **修订号**: 向下兼容的问题修复

### 变更类型
- **新增**: 新功能
- **改进**: 现有功能的改进
- **修复**: Bug 修复
- **变更**: 不影响功能的变更
- **废弃**: 即将移除的功能
- **移除**: 已移除的功能
- **安全**: 安全相关的修复

---

## 路线图

### [1.3.0] - 计划中 🔜
- 图片下载优化（非阻塞）
- 大书籍分批处理
- 缓存淘汰策略
- 性能基准测试

### [1.4.0] - 计划中 🔜
- 搜索功能
- 书籍推荐
- 阅读进度同步
- 统计面板

### [2.0.0] - 目标 🎯
- 完整测试覆盖
- 性能优化
- 文档完善
- 正式发布

---

**维护者**: HIUEETR  
**源代码**: https://github.com/HIUEETR/astrbot_plugin_esjzone_downloader  
**原始项目**: https://github.com/HIUEETR/esjzone-novel-downloader
