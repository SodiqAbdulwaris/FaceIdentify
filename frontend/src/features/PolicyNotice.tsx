import type { PolicyProvenance } from '@/api/types'

/** The policy the results came from: the person's own choice by name, the development policy, or a neutral word for any other. */
function policyName(version: string | null | undefined): string {
  if (version === 'buffalo-l-verified-match-v1') return 'the Automatic recognition you chose'
  if (version === 'buffalo-l-abstain-only-v1') return 'the Assisted recognition you chose'
  if (version?.startsWith('development-')) return `the development policy (${version})`
  return version ? `a policy that is installed (${version})` : 'an installed policy'
}

/**
 * The owner's decision (plan, decision 1): results from the development policy are labelled as
 * uncalibrated wherever they are shown. The label comes from the run's own frozen configuration,
 * so it cannot be wrong about which policy produced a result.
 */
export function PolicyNotice({ policy }: { policy: PolicyProvenance | undefined }) {
  if (policy === undefined || (policy.calibrated && policy.automatic_matching)) return null
  return (
    <div
      role="note"
      className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-950 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-100"
    >
      {policy.calibrated ? null : (
        <p>
          <strong>Uncalibrated results.</strong> These were produced with{' '}
          {policyName(policy.decision_policy_version)}, whose similarity scores have not been
          calibrated or validated: a high score is a reason to look, not proof. They are for
          evaluation only, not for real decisions.
        </p>
      )}
      {policy.automatic_matching ? null : (
        <p>
          <strong>Automatic matching disabled.</strong> A new face is never matched to an existing
          person automatically; a face that resembles someone waits for you to place it. Similarity
          scores are not probabilities.
        </p>
      )}
    </div>
  )
}
