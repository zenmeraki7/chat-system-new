import { appStore } from "../state/appStore";

type OptimisticMutation<T> = {
  entity: "campaigns" | "contacts" | "conversations" | "messages" | "templates" | "users";
  id: string;
  optimisticPatch: Record<string, unknown>;
  run: () => Promise<T>;
  rollbackPatch?: Record<string, unknown>;
};

const queue: Promise<unknown>[] = [];

export function runOptimisticMutation<T>(mutation: OptimisticMutation<T>): Promise<T> {
  appStore.patchEntity(mutation.entity, mutation.id, { ...mutation.optimisticPatch, __optimistic: true });
  const task = mutation.run()
    .then((result: any) => {
      appStore.patchEntity(mutation.entity, mutation.id, { ...(result || {}), __optimistic: false, __lastMutationError: undefined });
      return result as T;
    })
    .catch((error) => {
      appStore.patchEntity(mutation.entity, mutation.id, { ...(mutation.rollbackPatch || {}), __optimistic: false, __lastMutationError: String(error?.message || error) });
      throw error;
    });
  queue.push(task);
  task.finally(() => {
    const index = queue.indexOf(task);
    if (index >= 0) queue.splice(index, 1);
  });
  return task;
}

export const pendingMutationCount = () => queue.length;
