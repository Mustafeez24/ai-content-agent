"use client";

import { useState, type FormEvent } from "react";
import { addNote } from "@/lib/api";
import type { Note } from "@/lib/types";

export default function NotesThread({ contentId, initialNotes }: { contentId: string; initialNotes: Note[] }) {
  const [notes, setNotes] = useState<Note[]>(initialNotes);
  const [text, setText] = useState("");
  const [author, setAuthor] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!text.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      const note = await addNote(contentId, text.trim(), author.trim() || undefined);
      setNotes((prev) => [...prev, note]);
      setText("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add note.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-3">
      <ul className="space-y-2">
        {notes.map((note) => (
          <li key={note.id} className="rounded border border-slate-200 bg-slate-50 p-2 text-sm">
            <div className="mb-1 text-xs text-slate-500">
              {note.author} · {new Date(note.created_at).toLocaleString()}
            </div>
            <div>{note.note}</div>
          </li>
        ))}
        {notes.length === 0 && <li className="text-sm text-slate-400">No notes yet.</li>}
      </ul>
      <form onSubmit={submit} className="space-y-2">
        <input
          type="text"
          placeholder="Your name (optional)"
          aria-label="Author"
          value={author}
          onChange={(e) => setAuthor(e.target.value)}
          className="w-full rounded border border-slate-300 px-2 py-1 text-sm"
        />
        <textarea
          placeholder="Add an internal note..."
          aria-label="Note"
          value={text}
          onChange={(e) => setText(e.target.value)}
          className="w-full rounded border border-slate-300 px-2 py-1 text-sm"
          rows={2}
        />
        <button
          type="submit"
          disabled={submitting || !text.trim()}
          className="rounded bg-slate-900 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
        >
          Add note
        </button>
        {error && <p className="text-sm text-red-600">{error}</p>}
      </form>
    </div>
  );
}
