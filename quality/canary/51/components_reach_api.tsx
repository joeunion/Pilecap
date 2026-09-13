import { listDeals } from "@/api/client";

export function DealCard() {
  return listDeals ? null : null;
}
