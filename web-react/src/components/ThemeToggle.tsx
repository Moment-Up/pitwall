import { Button } from "@heroui/react";
import { Moon, Sun } from "@gravity-ui/icons";
import { useTheme } from "../hooks/stores";
import { theme } from "../lib/theme";

export function ThemeToggle() {
  const current = useTheme();
  const next = current === "dark" ? "light" : "dark";
  return (
    <Button
      isIconOnly
      variant="ghost"
      aria-label={`Switch to ${next} theme`}
      onPress={() => theme.toggle()}
      className="size-[var(--pw-touch)] rounded-full"
    >
      {current === "dark" ? <Sun aria-hidden="true" /> : <Moon aria-hidden="true" />}
    </Button>
  );
}
