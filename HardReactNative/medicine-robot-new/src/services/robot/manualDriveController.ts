import type { MovementResponse } from "@/src/types";

export type ManualDriveState =
  | "MANUAL_FORWARD"
  | "MANUAL_BACKWARD"
  | "MANUAL_LEFT"
  | "MANUAL_RIGHT"
  | "MANUAL_FORWARD_LEFT"
  | "MANUAL_FORWARD_RIGHT"
  | "MANUAL_BACKWARD_LEFT"
  | "MANUAL_BACKWARD_RIGHT"
  | "MANUAL_STOP";

export interface HeldDirections {
  forward: boolean;
  backward: boolean;
  left: boolean;
  right: boolean;
}

export const createEmptyHeldDirections = (): HeldDirections => ({
  forward: false,
  backward: false,
  left: false,
  right: false,
});

export const resolveManualDriveState = ({
  forward,
  backward,
  left,
  right,
}: HeldDirections): ManualDriveState => {
  if (forward && backward) return "MANUAL_STOP";

  const lateralDirection = left === right ? null : left ? "LEFT" : "RIGHT";

  if (forward) {
    if (lateralDirection === "LEFT") return "MANUAL_FORWARD_LEFT";
    if (lateralDirection === "RIGHT") return "MANUAL_FORWARD_RIGHT";
    return "MANUAL_FORWARD";
  }

  if (backward) {
    if (lateralDirection === "LEFT") return "MANUAL_BACKWARD_LEFT";
    if (lateralDirection === "RIGHT") return "MANUAL_BACKWARD_RIGHT";
    return "MANUAL_BACKWARD";
  }

  if (lateralDirection === "LEFT") return "MANUAL_LEFT";
  if (lateralDirection === "RIGHT") return "MANUAL_RIGHT";
  return "MANUAL_STOP";
};

interface ManualDriveDispatcherOptions {
  sendManual: (state: ManualDriveState) => Promise<MovementResponse>;
  sendEmergencyStop: () => Promise<MovementResponse>;
  onSuccess?: (state: ManualDriveState, emergency: boolean) => void;
  onError?: (
    error: unknown,
    state: ManualDriveState,
    emergency: boolean,
  ) => void;
}

export class LatestManualDriveDispatcher {
  private desiredState: ManualDriveState = "MANUAL_STOP";
  private desiredRevision = 0;
  private attemptedRevision = 0;
  private pendingEmergencyRevision: number | null = null;
  private running = false;
  private readonly idleResolvers: (() => void)[] = [];

  constructor(private readonly options: ManualDriveDispatcherOptions) {}

  setDesired(state: ManualDriveState, force = false): void {
    if (!force && state === this.desiredState) return;

    this.desiredState = state;
    this.desiredRevision += 1;
    this.startDrain();
  }

  emergencyStop(): void {
    this.desiredState = "MANUAL_STOP";
    this.desiredRevision += 1;
    this.pendingEmergencyRevision = this.desiredRevision;
    this.startDrain();
  }

  waitForIdle(): Promise<void> {
    if (!this.running && !this.hasPendingWork()) return Promise.resolve();
    return new Promise((resolve) => this.idleResolvers.push(resolve));
  }

  private hasPendingWork(): boolean {
    return (
      this.pendingEmergencyRevision !== null ||
      this.attemptedRevision !== this.desiredRevision
    );
  }

  private startDrain(): void {
    if (this.running) return;
    void this.drain();
  }

  private async drain(): Promise<void> {
    this.running = true;

    try {
      while (this.hasPendingWork()) {
        if (this.pendingEmergencyRevision !== null) {
          const revision = this.pendingEmergencyRevision;
          this.pendingEmergencyRevision = null;
          await this.dispatch(
            revision,
            "MANUAL_STOP",
            true,
            this.options.sendEmergencyStop,
          );
          continue;
        }

        const revision = this.desiredRevision;
        const state = this.desiredState;
        await this.dispatch(revision, state, false, () =>
          this.options.sendManual(state),
        );
      }
    } finally {
      this.running = false;
      if (this.hasPendingWork()) {
        this.startDrain();
      } else {
        this.idleResolvers.splice(0).forEach((resolve) => resolve());
      }
    }
  }

  private async dispatch(
    revision: number,
    state: ManualDriveState,
    emergency: boolean,
    request: () => Promise<MovementResponse>,
  ): Promise<void> {
    try {
      const result = await request();
      if (!result.success) {
        throw new Error("The robot API rejected the manual drive command.");
      }
      if (revision === this.desiredRevision) {
        this.options.onSuccess?.(state, emergency);
      }
    } catch (error) {
      if (revision === this.desiredRevision) {
        this.options.onError?.(error, state, emergency);
      }
    } finally {
      this.attemptedRevision = Math.max(this.attemptedRevision, revision);
    }
  }
}
