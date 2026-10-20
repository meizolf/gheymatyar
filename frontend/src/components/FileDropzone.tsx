import { useId, useRef, type ChangeEvent, type DragEvent } from 'react'
import { formatFileSize } from '../utils/format'
import { Button } from './ui/Button'

interface Props {
  label: string
  accept: string
  /** Local file chosen for upload (may not be accepted yet). */
  pendingFile?: File | null
  /** Filename confirmed by the backend. */
  acceptedFilename?: string | null
  uploading?: boolean
  disabled?: boolean
  error?: string | null
  onSelect: (file: File) => void
  onClear?: () => void
  hint?: string
}

export function FileDropzone({
  label,
  accept,
  pendingFile = null,
  acceptedFilename = null,
  uploading = false,
  disabled,
  error,
  onSelect,
  onClear,
  hint,
}: Props) {
  const inputId = useId()
  const inputRef = useRef<HTMLInputElement>(null)

  function handleFiles(list: FileList | File[] | null) {
    if (!list || list.length === 0) return
    onSelect(list[0]!)
  }

  function onChange(e: ChangeEvent<HTMLInputElement>) {
    handleFiles(e.target.files)
    e.target.value = ''
  }

  function onDrop(e: DragEvent) {
    e.preventDefault()
    if (disabled) return
    handleFiles(e.dataTransfer.files)
  }

  const showPending =
    pendingFile &&
    (!acceptedFilename || pendingFile.name !== acceptedFilename || Boolean(error))
  const displayName = showPending
    ? pendingFile.name
    : acceptedFilename

  return (
    <div className="file-drop">
      <label htmlFor={inputId} className="file-drop-label">
        {label}
      </label>
      <div
        className={`file-drop-zone${error ? ' has-error' : ''}${disabled ? ' is-disabled' : ''}`}
        onDragOver={(e) => e.preventDefault()}
        onDrop={onDrop}
      >
        <input
          ref={inputRef}
          id={inputId}
          type="file"
          accept={accept}
          disabled={disabled}
          onChange={onChange}
          className="file-drop-input"
        />
        {displayName ? (
          <div className="file-drop-meta">
            <div className="file-name ltr">{displayName}</div>
            {showPending && pendingFile ? (
              <div className="file-size">{formatFileSize(pendingFile.size)}</div>
            ) : null}
            <div className="file-status">
              {uploading
                ? 'در حال ارسال…'
                : error
                  ? 'پذیرفته نشد — فایل قبلی سرور حفظ شده است'
                  : acceptedFilename
                    ? 'پذیرفته‌شده توسط سرور'
                    : 'در انتظار ارسال'}
            </div>
            <div className="file-drop-actions">
              <Button
                size="sm"
                variant="secondary"
                disabled={disabled}
                onClick={() => inputRef.current?.click()}
              >
                تعویض فایل
              </Button>
              {onClear ? (
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={disabled}
                  onClick={onClear}
                >
                  حذف
                </Button>
              ) : null}
            </div>
          </div>
        ) : (
          <div className="file-drop-empty">
            <p>فایل را اینجا رها کنید یا انتخاب کنید</p>
            <Button
              size="sm"
              variant="secondary"
              disabled={disabled}
              onClick={() => inputRef.current?.click()}
            >
              انتخاب فایل
            </Button>
          </div>
        )}
      </div>
      {hint ? <p className="field-hint">{hint}</p> : null}
      {error ? (
        <p className="field-error" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  )
}
