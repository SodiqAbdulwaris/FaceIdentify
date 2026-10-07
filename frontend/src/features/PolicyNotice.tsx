import type { PolicyProvenance } from '@/api/types'

/**
 * The owner's decision (plan, decision 1): results from the development policy are labelled as
 * uncalibrated wherever they are shown. The label comes from the run's own frozen configuration,
 * so it cannot be wrong about which policy produced a result.
 */
export function PolicyNotice({ policy }: { policy: PolicyProvenance | undefined }) {
  if (policy === undefined || policy.calibrated) return null
  return (
    <div
      role="note"
      className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-950 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-100"
    >
      <strong>Uncalibrated results.</strong> These were produced with the development policy
      {policy.decision_policy_version ? ` (${policy.decision_policy_version})` : ''}, which has not
      been calibrated or validated. They are for evaluation only, not for real decisions.
    </div>
  )
}
