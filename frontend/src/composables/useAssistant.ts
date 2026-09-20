import { ref } from 'vue'

const open = ref(false)
const pending = ref('')

export function useAssistant() {
  function ask(text: string) {
    pending.value = text
    open.value = true
  }

  function toggle(value?: boolean) {
    open.value = value ?? !open.value
  }

  /** ChatBox 取走预填问题后清空，避免下次展开重复填入 */
  function takePending(): string {
    const text = pending.value
    pending.value = ''
    return text
  }

  return { open, pending, ask, toggle, takePending }
}
