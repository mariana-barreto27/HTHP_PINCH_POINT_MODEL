"""Categorias de falha: não convergir não demonstra impossibilidade física."""

class PhysicalConstraintError(ValueError):
    pass


class SolverConvergenceError(ValueError):
    pass


class SearchFailureError(SolverConvergenceError):
    pass


def failure_status(error):
    if isinstance(error,PhysicalConstraintError):
        return 'constraint_violation'
    if isinstance(error,SolverConvergenceError):
        return 'not_converged'
    return 'evaluation_error'
