# GitHub 首版发布流程（AStock-Daily-Forge）

## 1. 本地最终检查

```powershell
cd D:\AStock-Daily-Forge
C:\Users\shawn\AppData\Roaming\Python\Python314\Scripts\ruff.exe check src
C:\Users\shawn\AppData\Roaming\Python\Python314\Scripts\pytest.exe -q src\tests
```

## 2. 处理 Git 安全目录（如提示 dubious ownership）

```powershell
git config --global --add safe.directory D:/AStock-Daily-Forge
```

## 3. 初始化与提交（首次）

```powershell
cd D:\AStock-Daily-Forge
git init -b main
git add .
git commit -m "chore: prepare v1.1 release (docs, scheduler, assembler, ci)"
```

> 如果仓库已初始化，把 `git init -b main` 跳过即可。

## 4. 关联远程仓库并推送

```powershell
git remote add origin <你的仓库地址>
git push -u origin main
```

## 5. 在 GitHub 验证

- 打开仓库的 **Actions** 页面
- 确认 `CI` 工作流运行成功（Ruff + Pytest）
- 检查 README 渲染和目录结构

## 6. 打标签发布（可选）

```powershell
git tag -a v1.1.0 -m "AStock-Daily-Forge v1.1.0"
git push origin v1.1.0
```

## 7. 发布后建议

- 在仓库创建 `Issues` 模板（Bug/Feature）
- 增加 `CODEOWNERS`（如你后续多人协作）
- 为定时任务加失败告警（邮件/飞书/企业微信）
