import { useState } from 'react'

/** Functional composer (mock chat-1b.html .input/.input-inner tokens). */
export interface ChatInputProps {
  onSubmit: (query: string) => void
  /** True while a stream is in flight — one question at a time. */
  disabled: boolean
  placeholder: string
}

export function ChatInput({ onSubmit, disabled, placeholder }: ChatInputProps) {
  const [value, setValue] = useState('')

  const submit = () => {
    const query = value.trim()
    if (!query || disabled) return
    onSubmit(query)
    setValue('')
  }

  return (
    <div className="border-t border-border bg-bg px-[34px] pb-5 pt-4">
      <div className="mx-auto flex max-w-[760px] items-center gap-[10px] rounded-[13px] border border-border-strong bg-surface py-[11px] pl-4 pr-3">
        <input
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') submit()
          }}
          placeholder={placeholder}
          className="flex-1 bg-transparent text-[14.5px] text-text outline-none placeholder:text-faint"
        />
        <button
          type="button"
          onClick={submit}
          disabled={disabled || value.trim() === ''}
          className="shrink-0 rounded-[9px] bg-accent px-[14px] py-[9px] text-[14px] font-semibold text-accent-on disabled:cursor-default disabled:opacity-50"
        >
          Preguntar
        </button>
      </div>
    </div>
  )
}
