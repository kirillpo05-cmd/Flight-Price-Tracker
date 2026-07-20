import { useEffect, useRef, useState } from 'react'
import { AIRPORTS, Airport } from '../data/airports'

function findAirport(code: string): Airport | undefined {
  return AIRPORTS.find((a) => a.code === code.toUpperCase())
}

function label(a: Airport): string {
  return `${a.city} (${a.code})`
}

export function AirportAutocomplete({
  value,
  onChange,
  placeholder,
}: {
  value: string
  onChange: (code: string) => void
  placeholder?: string
}) {
  const known = findAirport(value)
  const [query, setQuery] = useState(known ? label(known) : value)
  const [open, setOpen] = useState(false)
  const [highlight, setHighlight] = useState(0)
  const boxRef = useRef<HTMLDivElement>(null)

  // Keep the displayed text in sync when the code changes from outside (e.g. swap button)
  useEffect(() => {
    const a = findAirport(value)
    setQuery(a ? label(a) : value)
  }, [value])

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', onClickOutside)
    return () => document.removeEventListener('mousedown', onClickOutside)
  }, [])

  const q = query.trim().toLowerCase()
  const matches =
    q.length === 0
      ? []
      : AIRPORTS.filter(
          (a) =>
            a.city.toLowerCase().startsWith(q) ||
            a.city.toLowerCase().includes(q) ||
            a.code.toLowerCase() === q ||
            a.country.toLowerCase().startsWith(q)
        ).slice(0, 8)

  const select = (a: Airport) => {
    onChange(a.code)
    setQuery(label(a))
    setOpen(false)
  }

  return (
    <div className="relative" ref={boxRef}>
      <input
        value={query}
        onChange={(e) => {
          const text = e.target.value
          setQuery(text)
          setOpen(true)
          setHighlight(0)
          const raw = text.trim().toUpperCase()
          // Allow typing a raw 3-letter IATA code directly for airports not in the list
          onChange(/^[A-Z]{3}$/.test(raw) ? raw : '')
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (!open || matches.length === 0) return
          if (e.key === 'ArrowDown') {
            e.preventDefault()
            setHighlight((h) => Math.min(h + 1, matches.length - 1))
          } else if (e.key === 'ArrowUp') {
            e.preventDefault()
            setHighlight((h) => Math.max(h - 1, 0))
          } else if (e.key === 'Enter') {
            e.preventDefault()
            select(matches[highlight])
          } else if (e.key === 'Escape') {
            setOpen(false)
          }
        }}
        placeholder={placeholder}
        required
        autoComplete="off"
        className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
      />
      {open && q.length > 0 && (
        <ul className="absolute z-10 mt-1 w-full max-h-56 overflow-auto bg-white border border-gray-200 rounded-lg shadow-lg text-sm">
          {matches.length > 0 ? (
            matches.map((a, i) => (
              <li
                key={a.code}
                onMouseDown={(e) => {
                  e.preventDefault()
                  select(a)
                }}
                className={`px-3 py-2 cursor-pointer flex items-center justify-between ${
                  i === highlight ? 'bg-blue-50' : 'hover:bg-gray-50'
                }`}
              >
                <span>
                  {a.city}
                  <span className="text-gray-400">, {a.country}</span>
                </span>
                <span className="font-mono text-gray-500">{a.code}</span>
              </li>
            ))
          ) : (
            <li className="px-3 py-2 text-gray-400">
              Not found — you can still type a 3-letter IATA code
            </li>
          )}
        </ul>
      )}
    </div>
  )
}
