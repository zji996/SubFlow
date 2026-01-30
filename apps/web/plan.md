# SubFlow 前端解耦计划

## 背景

当前前端代码存在以下耦合问题：
1. 工具函数在多个组件中重复定义（时间格式化、文件名提取等）
2. API 调用逻辑直接嵌入页面组件，缺乏抽象层
3. 类型定义分散在 API 文件和组件文件中
4. 组件内联样式与 CSS 类混用，样式逻辑不统一
5. 部分组件职责过重，UI 渲染与业务逻辑混杂

---

## 任务一：提取公共工具函数

### 目标
将分散在各组件中的工具函数统一提取到 `utils/` 目录。

### 需要提取的函数类别
1. **时间格式化类**：`formatTime`、`formatDuration`、`formatTimestamp`、`formatRelativeTime`
2. **字符串处理类**：`getMediaName`（从 URL 提取文件名）
3. **进度计算类**：`getProgress`（根据项目状态计算进度百分比）

### 约束
- 保持函数签名向后兼容
- 添加 JSDoc 注释说明用途
- 导出一个统一的入口文件 `utils/index.ts`

### 验收标准
- [ ] 所有工具函数集中在 `utils/` 目录
- [ ] 原组件通过导入使用，不再内联定义
- [ ] TypeScript 编译通过，无运行时错误

---

## 任务二：创建自定义 Hooks 抽象 API 调用

### 目标
为每个主要数据实体创建自定义 Hook，封装数据获取、状态管理和错误处理逻辑。

### 需要创建的 Hooks
1. **useProject(projectId)** - 获取单个项目详情，支持轮询
2. **useProjects()** - 获取项目列表，支持排序、轮询
3. **useSubtitles(projectId)** - 获取字幕编辑数据
4. **useExports(projectId)** - 获取导出历史
5. **usePreview(projectId)** - 获取预览数据和分页段落

### 每个 Hook 应返回
```typescript
{
  data: T | null
  loading: boolean
  error: string | null
  refetch: () => void
  // 特定操作方法（如 deleteProject, runStage 等）
}
```

### 约束
- 复用现有的 `usePolling` Hook
- 操作方法（mutations）应处理 loading 和 error 状态
- 支持乐观更新模式（可选）

### 验收标准
- [ ] 页面组件不再直接调用 `apiRequest` 或 API 函数
- [ ] 数据获取逻辑与 UI 渲染完全分离
- [ ] Hook 可独立测试

---

## 任务三：统一类型定义

### 目标
将所有共享类型定义集中到 `types/` 目录。

### 类型分类
1. **entities.ts** - 核心业务实体（Project, Stage, Subtitle 等）
2. **api.ts** - API 请求/响应类型
3. **components.ts** - 组件 Props 类型（可选，视情况保留在组件文件中）

### 约束
- API 文件只保留请求函数，类型从 `types/` 导入
- 避免循环依赖

### 验收标准
- [ ] 所有实体类型有单一来源
- [ ] API 文件精简为纯函数文件
- [ ] IDE 类型推断正常工作

---

## 任务四：组件拆分与职责单一化

### 目标
将大型页面组件拆分为更小的、职责单一的子组件。

### 重点拆分对象

#### ProjectDetailPage
当前职责过多，应拆分为：
- `ProjectHeader` - 项目标题、状态、操作按钮
- `ProjectPipeline` - 阶段进度可视化
- `ProjectActions` - 操作按钮组（运行、重试、删除）
- `ProjectInfo` - 媒体信息、语言设置等

#### NewProjectPage  
应拆分为：
- `MediaUploader` - 文件上传/URL 输入（已有拖拽逻辑，可独立）
- `LanguageSelector` - 语言选择组合
- `ProjectForm` - 表单容器

### 约束
- 子组件通过 Props 接收数据和回调，不直接调用 API
- 保持组件目录结构清晰：`components/project/`、`components/form/` 等

### 验收标准
- [ ] 每个组件代码不超过 200 行
- [ ] 组件可独立复用
- [ ] Props 接口清晰，有 TypeScript 类型

---

## 任务五：样式规范化

### 目标
减少内联样式的使用，统一采用 CSS 类。

### 方法
1. 审查高频使用的内联样式模式
2. 在 `components.css` 中创建对应的工具类
3. 替换组件中的内联样式为类名

### 常见需要类化的模式
- 颜色变量引用：`text-[--color-text-muted]` → `.text-muted`
- 间距组合：`px-4 py-3` → `.card-padding`
- 玻璃态效果变体：不同透明度、边框的 `glass-card` 变体

### 约束
- 不要过度抽象，只提取使用 3 次以上的模式
- 保持与现有设计系统一致

### 验收标准
- [ ] 内联样式使用减少 50% 以上
- [ ] 新增工具类有明确命名约定
- [ ] 视觉效果与修改前完全一致

---

## 执行顺序建议

1. **任务三**（类型统一）→ 为后续工作奠定基础
2. **任务一**（工具函数）→ 简单且影响面广
3. **任务二**（自定义 Hooks）→ 核心解耦
4. **任务四**（组件拆分）→ 依赖 Hooks 完成后进行
5. **任务五**（样式规范化）→ 最后打磨

---

## 验证方式

每完成一个任务后：
1. 运行 `npm run build` 确保无编译错误
2. 运行开发服务器手动验证功能正常
3. 检查浏览器控制台无运行时错误

---

## 不在本次范围内

- 状态管理库引入（如 Zustand/Redux）- 当前规模不需要
- 测试编写 - 可作为后续任务
- 性能优化（懒加载、虚拟列表等）- 当前数据量不需要
