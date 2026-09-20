import Link from "next/link";
import type { ContentItem } from "@/lib/types";
import StatusBadge from "./StatusBadge";

export default function ContentTable({ items }: { items: ContentItem[] }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
      <table className="min-w-full divide-y divide-slate-200 text-sm">
        <thead className="bg-slate-50">
          <tr>
            <th className="px-3 py-2 text-left font-medium text-slate-600">Day</th>
            <th className="px-3 py-2 text-left font-medium text-slate-600">Date</th>
            <th className="px-3 py-2 text-left font-medium text-slate-600">Platform</th>
            <th className="px-3 py-2 text-left font-medium text-slate-600">Type</th>
            <th className="px-3 py-2 text-left font-medium text-slate-600">Topic</th>
            <th className="px-3 py-2 text-left font-medium text-slate-600">Priority</th>
            <th className="px-3 py-2 text-left font-medium text-slate-600">Status</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {items.map((item) => (
            <tr key={item.id} className="hover:bg-slate-50">
              <td className="px-3 py-2">{item.day_number}</td>
              <td className="px-3 py-2">{item.date}</td>
              <td className="px-3 py-2">{item.platform}</td>
              <td className="px-3 py-2">{item.content_type}</td>
              <td className="px-3 py-2">
                <Link href={`/content/${item.id}`} className="text-sky-600 hover:underline">
                  {item.topic}
                </Link>
              </td>
              <td className="px-3 py-2 capitalize">{item.priority}</td>
              <td className="px-3 py-2">
                <StatusBadge status={item.workflow_status} />
              </td>
            </tr>
          ))}
          {items.length === 0 && (
            <tr>
              <td colSpan={7} className="px-3 py-6 text-center text-slate-400">
                No content matches these filters.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
