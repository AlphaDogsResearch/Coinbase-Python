import os
import threading


def pytest_sessionfinish(session, exitstatus):
    """
    Called after the whole test run finishes (all tests done, summary printed).
    exitstatus: 0=passed, 1=failed, etc.
    """
    print("\nAll tests finished! You can run cleanup or logging here.")
    if exitstatus == 0:
        print("All tests passed successfully!")
    else:
        print(f"Tests finished with exit status {exitstatus}")

    for thread in threading.enumerate():
        print(thread.name)

    # all_child_threads = [thread for thread in threading.enumerate() if thread != threading.main_thread()]
    # for thread in all_child_threads:
    #     print(thread.name)
    #     if 'pydevd' not in thread.name:
    #         thread.daemon = True
    # Example: terminate background processes if needed
    # import os
    os._exit(0)  # only if you really want to kill everything