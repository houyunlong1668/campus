import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js'

// 单实例共享：每个气泡各建一个带全量 hljs 的 parser 会随消息数线性放大开销
export const md = new MarkdownIt({
  html: false, // 硬约束：模型输出直插 DOM 是 XSS 入口
  highlight(code, lang) {
    const language = hljs.getLanguage(lang) ? lang : 'plaintext'
    return `<pre><code class="hljs">${hljs.highlight(code, { language }).value}</code></pre>`
  },
})
