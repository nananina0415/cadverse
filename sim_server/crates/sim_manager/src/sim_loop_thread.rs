fn make_sim_loop_thread(input)->Thread{
    let simulator = Simulator::new();
    loop {
        simulator.step(input.read())
    }
}
