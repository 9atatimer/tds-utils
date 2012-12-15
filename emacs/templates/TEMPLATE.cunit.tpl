/*
 *  CUnit tests for hw_flags.c
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>

#include <CUnit/CUnit.h>
#define TEST_REF(A)  #A, A

/* Suite initialization/cleanup functions */
static int testsuite_setup(void) { return 0; }
static int testsuite_teardown(void) { return 0; }

static void pertest_setup(void) { }
static void pertest_teardown(void) { }

static void testInit(void)
{
  
}

static CU_TestInfo basic_tests[] = {
  { TEST_REF(testInit) }
  /* add unit tests here */
  CU_TEST_INFO_NULL,
};

static CU_SuiteInfo suite_info[] = {
  { TEST_LABEL(basic_suite),
    testsuite_setup, testsuite_teardown,
    pertest_setup, pertest_teardown,
    basic_tests},
  /* add new test suites if needed */
  CU_SUITE_INFO_NULL,
};

extern void SUITE_ENTRYPOINT()
{
  assert(NULL != CU_get_registry());
  assert(!CU_is_test_running());

  /* Register suites. */
  if (CU_register_suites(suites) != CUE_SUCCESS) {
    fprintf(stderr, "suite registration failed - %s\n",
	    CU_get_error_msg());
    exit(EXIT_FAILURE);
  }
}
