import { DISCLAIMER } from "../../labels";

type Props = {
  compact?: boolean;
  text?: string;
};

export function Disclaimer({ compact, text }: Props) {
  return (
    <p className={`disclaimer ${compact ? "compact" : ""}`}>
      {text || DISCLAIMER}
    </p>
  );
}
