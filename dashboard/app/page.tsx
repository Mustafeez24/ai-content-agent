import BreakdownList from "@/components/BreakdownList";
import StatCard from "@/components/StatCard";
import { getDashboardSummary } from "@/lib/api";

export default async function DashboardPage() {
  const summary = await getDashboardSummary();

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Dashboard</h1>
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
        <StatCard label="Total content items" value={summary.total_content_items} />
        <StatCard label="Pending review" value={summary.pending_review} />
        <StatCard label="Approved" value={summary.approved} />
        <StatCard label="Scheduled" value={summary.scheduled} />
        <StatCard label="Published" value={summary.published} />
        <StatCard label="Changes requested" value={summary.changes_requested} />
        <StatCard label="QA passed (not yet reviewed)" value={summary.qa_passed} />
        <StatCard label="QA warnings (latest import)" value={summary.qa_warnings} />
      </div>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <BreakdownList title="Platform breakdown" data={summary.platform_breakdown} />
        <BreakdownList title="Content-type breakdown" data={summary.content_type_breakdown} />
      </div>
    </div>
  );
}
