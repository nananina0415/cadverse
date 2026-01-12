# Simulation Flow

## Initialization

1. Load metadata JSON
2. Create ChSystemNSC
3. Create bodies
4. Create joints and constraints
5. Create actuators

## Runtime Loop

1. Receive user input (AR / server)
2. Apply control (torque / motor speed)
3. Call DoStepDynamics(dt)
4. Read body states
5. Export PartState list

## Shutdown

- Clear Chrono system
- Release resources
