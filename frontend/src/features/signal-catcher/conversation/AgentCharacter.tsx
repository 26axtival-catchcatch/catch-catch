import type { AgentActivity } from "../../customer-intelligence/agent-activity";

/** Original Catch team characters. Appearance identifies a role, never a finding's confidence. */
export function AgentCharacter({ role }: { role: AgentActivity["role"] | "all" }) {
  if (role === "all") return <svg viewBox="0 0 64 64" fill="none" aria-hidden="true">
    <path d="M6 46V30a12 12 0 0 1 24 0v16" fill="var(--character-investigator)" />
    <path d="M35 46V29a12 12 0 0 1 24 0v17" fill="var(--character-verifier)" />
    <path d="M18 53V25a14 14 0 0 1 28 0v28c-8 5-20 5-28 0Z" fill="var(--character-coordinator)" />
    <g fill="var(--u-black)"><circle cx="27" cy="30" r="1.8" /><circle cx="37" cy="30" r="1.8" /><circle cx="12" cy="33" r="1.5" /><circle cx="52" cy="33" r="1.5" /></g>
    <path d="M28 37q4 3 8 0M32 11V6" stroke="var(--u-black)" strokeWidth="1.6" strokeLinecap="round" />
    <circle cx="32" cy="5" r="3" fill="var(--u-light)" />
  </svg>;

  return <svg viewBox="0 0 64 64" fill="none" aria-hidden="true">
    <ellipse cx="32" cy="58" rx="21" ry="3" fill="currentColor" opacity=".12" />
    <path d="M12 48V29C12 15 20 9 32 9s20 6 20 20v19c0 7-9 10-20 10S12 55 12 48Z" fill="currentColor" />
    <path d="M19 49v6m26-6v6" stroke="var(--u-black)" strokeOpacity=".18" strokeWidth="2" strokeLinecap="round" />
    <ellipse cx="20" cy="34" rx="3" ry="1.6" fill="var(--u-light)" opacity=".35" />
    <ellipse cx="44" cy="34" rx="3" ry="1.6" fill="var(--u-light)" opacity=".35" />
    <g fill="var(--u-black)"><ellipse cx="25" cy="28" rx="1.8" ry="2.4" /><ellipse cx="39" cy="28" rx="1.8" ry="2.4" /></g>
    <path d={role === "verifier" ? "M29 37h6" : "M28 36q4 4 8 0"} stroke="var(--u-black)" strokeWidth="1.7" strokeLinecap="round" />
    {role === "coordinator" ? <>
      <path d="M32 10V5M14 28v9h5M50 28v9h-5" stroke="var(--u-light)" strokeWidth="2.5" strokeLinecap="round" />
      <circle cx="32" cy="5" r="3" fill="var(--u-light)" />
      <path d="m28 47 4-4 4 4-4 4Z" fill="var(--u-light)" opacity=".8" />
    </> : null}
    {role === "investigator" ? <>
      <circle cx="40" cy="28" r="9" fill="var(--u-light)" fillOpacity=".15" stroke="var(--u-black)" strokeWidth="2" />
      <path d="m47 35 8 9" stroke="var(--u-black)" strokeWidth="4" strokeLinecap="round" />
      <path d="M18 19q6-3 10-1" stroke="var(--u-black)" strokeWidth="1.5" strokeLinecap="round" />
    </> : null}
    {role === "verifier" ? <>
      <g stroke="var(--u-black)" strokeWidth="1.7"><rect x="17" y="22" width="14" height="12" rx="4" /><rect x="33" y="22" width="14" height="12" rx="4" /><path d="M31 26h2M13 25h4m30 0h4" /></g>
      <path d="M25 46h14M25 50h10" stroke="var(--u-black)" strokeOpacity=".3" strokeWidth="1.5" strokeLinecap="round" />
    </> : null}
    {role === "reporter" ? <>
      <rect x="34" y="39" width="19" height="19" rx="3" fill="var(--u-light)" />
      <path d="M38 44h9m-9 4h9m-9 4h5M17 14l9-4" stroke="var(--u-black)" strokeWidth="1.5" strokeLinecap="round" />
      <path d="m48 50 7-11" stroke="var(--u-black)" strokeWidth="3" strokeLinecap="round" />
    </> : null}
  </svg>;
}
