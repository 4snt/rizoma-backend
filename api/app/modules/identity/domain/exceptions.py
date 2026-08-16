"""Exceções de domínio de identidade — `service.py` traduz para HTTP."""


class DomainNotAllowedError(Exception):
    """E-mail fora do domínio institucional permitido."""


class NotInvitedError(Exception):
    """Usuário novo sem convite pendente. Sem isso, qualquer pessoa do
    domínio criaria conta sozinha."""


class SlugTakenError(Exception):
    """Já existe organização com este slug."""


class AlreadyMemberError(Exception):
    """E-mail já é membro da organização — convite duplicado não faz sentido."""


class DuplicateInvitationError(Exception):
    """Já existe convite pendente para este e-mail nesta organização."""


class InvitationNotFoundError(Exception):
    """Convite não existe ou não pertence à organização do chamador."""


class MemberNotFoundError(Exception):
    """Usuário não é membro da organização do chamador."""


class CannotRemoveSelfError(Exception):
    """Admin não pode remover ou rebaixar a própria filiação por este endpoint
    — evita o próprio admin se trancar pra fora da organização sem querer."""
