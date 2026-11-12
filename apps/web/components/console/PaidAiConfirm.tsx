"use client";

import { Button } from "@/components/ui/controls";
import { Dialog } from "@/components/ui/overlay";
import { useI18n } from "@/lib/i18n/react";

/** Asks before an action that makes billed model calls (drafting pack items, running the eval set). */
export function PaidAiConfirm({ open, text, onConfirm, onClose }: { open: boolean; text: string; onConfirm: () => void; onClose: () => void }) {
  const { t } = useI18n();
  return (
    <Dialog
      open={open}
      title={t("ui.paidConfirmTitle")}
      onClose={onClose}
      actions={
        <>
          <Button onClick={onClose}>{t("ui.cancel")}</Button>
          <Button variant="primary" meta={t("ui.paidAi")} onClick={() => { onClose(); onConfirm(); }}>{t("ui.continue")}</Button>
        </>
      }
    >
      {text}
    </Dialog>
  );
}
