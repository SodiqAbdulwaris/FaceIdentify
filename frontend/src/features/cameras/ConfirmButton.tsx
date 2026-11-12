import { useEffect, useId, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'

/**
 * A button that asks first, in place. Asking moves focus to "Keep it" (the safe answer); Escape or
 * "Keep it" gives focus back to the button.
 */
export function ConfirmButton({
  label,
  question,
  confirm,
  onConfirm,
  disabled = false,
}: {
  label: string
  question: string
  confirm: string
  onConfirm: () => void
  disabled?: boolean
}) {
  const [asking, setAsking] = useState(false)
  const trigger = useRef<HTMLButtonElement>(null)
  const keep = useRef<HTMLButtonElement>(null)
  const returning = useRef(false)
  const warning = useId()

  useEffect(() => {
    if (asking) keep.current?.focus()
    else if (returning.current) {
      returning.current = false
      trigger.current?.focus()
    }
  }, [asking])

  const cancel = () => {
    returning.current = true
    setAsking(false)
  }

  if (!asking) {
    return (
      <Button
        ref={trigger}
        variant="outline"
        size="sm"
        disabled={disabled}
        onClick={() => setAsking(true)}
      >
        {label}
      </Button>
    )
  }
  return (
    <div
      role="group"
      aria-describedby={warning}
      className="flex flex-wrap items-center gap-2"
      onKeyDown={(event) => {
        if (event.key === 'Escape') cancel()
      }}
    >
      <span id={warning} className="text-sm">
        {question}
      </span>
      <Button
        variant="destructive"
        size="sm"
        onClick={() => {
          setAsking(false)
          onConfirm()
        }}
      >
        {confirm}
      </Button>
      <Button ref={keep} variant="outline" size="sm" onClick={cancel}>
        Keep it
      </Button>
    </div>
  )
}
