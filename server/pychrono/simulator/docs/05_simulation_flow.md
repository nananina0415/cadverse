# Simulation Flow

## Initialization

1. Load metadata JSON
2. Create ChSystemNSC
3. Create bodies
4. Create collision shapes & contact materials
5. Create joints and constraints
6. Create actuators
7. Cache metadata inertia (explicit) if needed
8. Configure system options (solver / iterations / etc.) if needed

## Runtime Loop

1. Receive user input (AR / server)
2. Coerce/parse user input (dict → runtime event types) if needed
3. Clear force/torque accumulators (binding compatibility) if possible
4. Apply control (torque / motor speed / AR interaction)
5. Call DoStepDynamics(dt)
6. Read body states
7. Export PartState list
8. (Optional) Export telemetry (contacts / reaction / etc.)

## Shutdown

- Clear Chrono system (Simulator.close() / sys.Clear())
- Release resources
