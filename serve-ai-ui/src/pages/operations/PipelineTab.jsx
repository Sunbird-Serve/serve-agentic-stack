/**
 * PipelineTab — Wraps the existing OpsView volunteer pipeline dashboard.
 * This preserves the full existing functionality without modification.
 */
import { OpsView } from '../../views/OpsView';

export function PipelineTab() {
  return <OpsView />;
}

export default PipelineTab;
