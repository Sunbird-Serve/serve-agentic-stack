/**
 * DashboardOverview — Admin dashboard with KPIs, funnel, and action queue.
 * Reuses the existing OpsView pipeline logic.
 */
import { OpsView } from '../../views/OpsView';

export function DashboardOverview() {
  return <OpsView />;
}

export default DashboardOverview;
