# UI Design System

## 大人确认的 UI 偏好（更新于 2026-10-22）

以下是大人明确提出的偏好，优先于下方通用设计建议：

- 整体简约、大气、安静；2026-10-22 大人最新确认采用蓝灰色，允许克制的色彩层次，不再要求全黑白。浅蓝灰背景、白色内容区，深蓝灰用于主操作、选中导航与进度；避免红色、粉色和多种高饱和强调色。
- 图标要重新设计成统一的简洁黑白图形，不使用 emoji，不照搬其他产品的品牌标志。
- Windows 软件首页参考本次提供的 ChatGPT 首页截图：居中的一句问候，下方一个链接输入框，输入框右侧为深蓝灰提交按钮，旁边保留独立粘贴按钮。
- 首页下方并排展示最近的三个真实作品缩略图，保持轻量，不增加卡片说明、体积、日期等冗余信息。
- 左侧参考 ChatGPT 的收起 / 展开交互：默认是顶部 Logo、竖排功能图标和底部账号 / 设置入口组成的窄栏；点击左上角图标展开整条全高侧栏，显示导航名称与最近作品，可再次收起。不要把展开导航做成小菜单。两种状态都以细竖线与主内容分隔。
- 收起的窄栏只保留下载、视频库、更新三个功能图标，去掉独立搜索图标；展开后的顶部搜索与视频库内搜索继续保留。
- 展开的侧栏随窗口宽度适配，也支持拖动分隔线调整并记住宽度。最近作品的长标题不撑宽、不折行；超出边缘渐隐裁切，从右向左单向循环滚动，不来回滑动。
- 搜索是独立浮层，用于快速查找并打开作品；视频库用于浏览、排序和管理，两个入口不应打开同一页面或同时呈现为选中导航。关闭搜索应保留原页面与筛选条件。
- 设置窗口要宽敞，默认 820×680，可手动调整大小，控件与按钮不拥挤、不裁切。
- Logo 使用轻盈、精致的原创黑白线条标志，不用厚重黑底方块、普通下载箭头或过于直白的工具图形充当品牌 Logo。
- 首页不要自行增加口号、副标题、平台徽章、快捷键教程、目录信息栏或“最近保存 / 查看全部”等辅助文案。
- 少文字、重布局和图标。大人明确要求时再添加解释性文字；按钮标签、真实进度和错误原因使用必要的短句。
- 视频库和查看窗口提供直接删除入口，图文支持单张图片删除；本地文件删除前确认，删除后及时刷新作品与缩略图。
- 打开视频后应能正常切回视频库，避免播放器一直盖住主界面；本轮使用可自由切换、最小化和最大化的独立播放窗口。
- 使用留白、对齐、字重和细边界建立层级，不使用装饰渐变、彩色光效或堆叠面板来制造高级感。
- UI 修改完成后先提供可运行的本地预览与实际截图，等待大人检查确认，再上线。

## 1. Design Direction

Create polished, premium, Apple-inspired interfaces.
The design should feel calm, precise, elegant, minimal, and highly usable. Prioritize typography, spacing, alignment, visual hierarchy, and meaningful interactions over decoration.
Use Apple design principles as inspiration. Do not blindly copy Apple's website or native iOS UI into unrelated products.

## 2. Inspect Before Coding

- Inspect the existing project structure, framework, dependencies, and styling conventions before making changes.
- Identify the current page entry points and shared components.
- Preserve existing functionality, business logic, routing, and data flows.
- Do not assume the project uses React, Vue, Tailwind, or any particular component library.
- Do not introduce new dependencies unless they provide clear value.
- Explain the implementation plan before a large visual refactor.

## 3. Visual Language

- Use a restrained neutral palette with a clear text hierarchy.
- Prefer clean backgrounds, subtle borders, carefully controlled contrast, and generous but purposeful whitespace.
- Use one primary accent color unless the product's existing brand requires otherwise.
- Keep content visually organized and easy to scan.
- Use gradients, blur, translucency, and shadows sparingly.
- Avoid generic AI-generated dashboard patterns, excessive cards, decorative gradients, glowing effects, oversized rounded pills, and unnecessary animations.
- Do not add decorative elements merely to fill empty space.

## 4. Typography

- Establish a consistent hierarchy for page titles, section headings, body text, labels, and secondary information.
- Prefer a suitable native system font stack for web interfaces unless the product has an established typography system.
- Use font weight and line height deliberately.
- Avoid excessive font sizes, inconsistent weights, and low-contrast secondary text.
- Ensure Chinese and English content both render naturally.

## 5. Layout and Spacing

- Use a consistent spacing scale based on 4px or 8px increments.
- Align page titles, content sections, controls, and navigation consistently.
- Give important content sufficient space.
- Avoid excessive empty space that weakens information density.
- Avoid cramming unrelated information into a single card.
- Use a consistent content width appropriate to the page.
- Make layouts responsive instead of fixing desktop dimensions.

## 6. Components

- Standardize buttons, inputs, dropdowns, dialogs, navigation, tables, and feedback messages.
- Use consistent heights, padding, borders, radii, and interaction states.
- Keep shadows subtle and use them only when they communicate depth.
- Provide clear hover, focus, active, disabled, loading, empty, success, and error states where applicable.
- Use the project's existing icon library when available. Do not replace interface icons with emoji.
- Make reusable components follow the same design tokens.

## 7. Accessibility and Responsiveness

- Maintain readable text and sufficient color contrast.
- Support keyboard navigation and visible focus states.
- Use semantic HTML and accessible labels.
- Test desktop, tablet, and mobile layouts where relevant.
- Prevent clipping, overlapping content, horizontal overflow, and broken long text.

## 8. Visual Quality Assurance

- Run the project using its existing development workflow.
- Inspect actual browser rendering when browser tooling is available.
- Capture screenshots at representative viewport sizes.
- Fix the largest visual problems first: layout, hierarchy, spacing, typography, then component details.
- Repeat screenshot inspection after meaningful changes.
- Never claim to have visually inspected a page if no screenshot or browser inspection was performed.
- Run appropriate tests and builds after implementation.

## 9. Definition of Done

The result should feel like a coherent, professionally designed commercial product, not a generic AI-generated template.
Visual consistency, usability, accessibility, responsiveness, and preservation of existing functionality are all required.
