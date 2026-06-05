"use client";

import { createContext, useContext, useState, ReactNode } from "react";

type Registration = { isStreaming: boolean; abort: () => void };

type ContextValue = {
  registration: Registration;
  register: (r: Registration) => void;
};

const WorkflowStateContext = createContext<ContextValue>({
  registration: { isStreaming: false, abort: () => {} },
  register: () => {},
});

export function WorkflowStateProvider({ children }: { children: ReactNode }) {
  const [registration, setRegistration] = useState<Registration>({
    isStreaming: false,
    abort: () => {},
  });

  return (
    <WorkflowStateContext.Provider
      value={{ registration, register: setRegistration }}
    >
      {children}
    </WorkflowStateContext.Provider>
  );
}

export function useWorkflowState() {
  return useContext(WorkflowStateContext);
}
