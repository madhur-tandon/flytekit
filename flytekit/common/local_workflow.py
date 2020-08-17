import uuid as _uuid
from typing import Any, Dict, List

import six as _six
from flyteidl.core import workflow_pb2 as _core_workflow_pb2
from six.moves import queue as _queue

from flytekit.common import interface as _interface
from flytekit.common import launch_plan as _launch_plan
from flytekit.common import nodes as _nodes
from flytekit.common import promise as _promise
from flytekit.common.core import identifier as _identifier
from flytekit.common.exceptions import user as _user_exceptions
from flytekit.common.mixins import hash as _hash_mixin
from flytekit.common.mixins import registerable as _registerable
from flytekit.common.types import helpers as _type_helpers
from flytekit.common.workflow import SdkWorkflow
from flytekit.configuration import internal as _internal_config
from flytekit.models import common as _common_models
from flytekit.models import interface as _interface_models
from flytekit.models import literals as _literal_models
from flytekit.models.core import identifier as _identifier_model
from flytekit.models.core import workflow as _workflow_models


# Local-only wrapper around binding data and variables. Note that the Output object used by the end user is a yet
# another layer on top of this.
class Output(object):
    def __init__(self, name, value, sdk_type=None, help=None):
        """
        :param Text name:
        :param T value:
        :param U sdk_type: If specified, the value provided must cast to this type.  Normally should be an instance of
            flytekit.common.types.base_sdk_types.FlyteSdkType.  But could also be something like:

            list[flytekit.common.types.base_sdk_types.FlyteSdkType],
            dict[flytekit.common.types.base_sdk_types.FlyteSdkType,flytekit.common.types.base_sdk_types.FlyteSdkType],
            (flytekit.common.types.base_sdk_types.FlyteSdkType, flytekit.common.types.base_sdk_types.FlyteSdkType, ...)
        """
        if sdk_type is None:
            # This syntax didn't work for some reason: sdk_type = sdk_type or Output._infer_type(value)
            sdk_type = Output._infer_type(value)
        sdk_type = _type_helpers.python_std_to_sdk_type(sdk_type)

        self._binding_data = _interface.BindingData.from_python_std(sdk_type.to_flyte_literal_type(), value)
        self._var = _interface_models.Variable(sdk_type.to_flyte_literal_type(), help or "")
        self._name = name

    def rename_and_return_reference(self, new_name):
        self._name = new_name
        return self

    @staticmethod
    def _infer_type(value):
        # TODO: Infer types
        raise NotImplementedError(
            "Currently the SDK cannot infer a workflow output type, so please use the type kwarg "
            "when instantiating an output."
        )

    @property
    def name(self):
        """
        :rtype: Text
        """
        return self._name

    @property
    def binding_data(self):
        """
        :rtype: flytekit.models.literals.BindingData
        """
        return self._binding_data

    @property
    def var(self):
        """
        :rtype: flytekit.models.interface.Variable
        """
        return self._var


class PythonWorkflow(_hash_mixin.HashOnReferenceMixin, _registerable.LocalEntity, _registerable.RegisterableEntity):
    """
    Wrapper class for locally defined Python workflows
    """

    def __init__(
        self, flyte_workflow: SdkWorkflow, inputs: List[_promise.Input], nodes: List[_nodes.SdkNode],
    ):
        _registerable.LocalEntity.__init__(self)
        # Currently experimenting with using composition instead of inheritance, which is why this has an sdk workflow.
        self._flyte_workflow = flyte_workflow
        self._workflow_inputs = inputs
        self._nodes = nodes
        self._user_inputs = inputs
        self._upstream_entities = set(n.executable_sdk_object for n in nodes)

    def __call__(self, *args, **input_map):
        # Take the default values from the Inputs
        compiled_inputs = {v.name: v.sdk_default for v in self.user_inputs if not v.sdk_required}
        compiled_inputs.update(input_map)

        return self.flyte_workflow.__call__(*args, **compiled_inputs)

    @property
    def flyte_workflow(self) -> SdkWorkflow:
        return self._flyte_workflow

    @classmethod
    def construct_from_class_definition(
        cls,
        inputs: List[_promise.Input],
        outputs: List[Output],
        nodes: List[_nodes.SdkNode],
        metadata: _workflow_models.WorkflowMetadata = None,
        metadata_defaults: _workflow_models.WorkflowMetadataDefaults = None,
    ) -> "PythonWorkflow":
        """
        This constructor is here to provide backwards-compatibility for class-defined Workflows

        :param list[flytekit.common.promise.Input] inputs:
        :param list[Output] outputs:
        :param list[flytekit.common.nodes.SdkNode] nodes:
        :param WorkflowMetadata metadata: This contains information on how to run the workflow.
        :param flytekit.models.core.workflow.WorkflowMetadataDefaults metadata_defaults: Defaults to be passed
            to nodes contained within workflow.
        :rtype: PythonWorkflow
        """
        for n in nodes:
            for upstream in n.upstream_nodes:
                if upstream.id is None:
                    raise _user_exceptions.FlyteAssertion(
                        "Some nodes contained in the workflow were not found in the workflow description.  Please "
                        "ensure all nodes are either assigned to attributes within the class or an element in a "
                        "list, dict, or tuple which is stored as an attribute in the class."
                    )

        id = _identifier.Identifier(
            _identifier_model.ResourceType.WORKFLOW,
            _internal_config.PROJECT.get(),
            _internal_config.DOMAIN.get(),
            _uuid.uuid4().hex,
            _internal_config.VERSION.get(),
        )
        interface = _interface.TypedInterface({v.name: v.var for v in inputs}, {v.name: v.var for v in outputs})

        output_bindings = [_literal_models.Binding(v.name, v.binding_data) for v in outputs]

        sdk_workflow = SdkWorkflow(
            id=id,
            metadata=metadata,
            metadata_defaults=metadata_defaults,
            interface=interface,
            nodes=nodes,
            output_bindings=output_bindings,
        )

        return cls(sdk_workflow, inputs, nodes)

    @property
    def nodes(self):
        return self.flyte_workflow.nodes

    @property
    def outputs(self):
        return self.flyte_workflow.outputs

    @property
    def upstream_entities(self):
        # TODO: Should we re-evaluate every time?
        # return set(n.executable_sdk_object for n in self.nodes)
        return self._upstream_entities

    @property
    def interface(self):
        return self.flyte_workflow.interface

    @property
    def id(self):
        return self.flyte_workflow.id

    @id.setter
    def id(self, new_id):
        self._flyte_workflow._id = new_id

    def register(self, *args, **kwargs):
        return self.flyte_workflow.register(*args, **kwargs)

    def serialize(self):
        return self.flyte_workflow.serialize()

    @property
    def user_inputs(self) -> List[_promise.Input]:
        """
        :rtype: list[flytekit.common.promise.Input]
        """
        return self._user_inputs

    def create_launch_plan(
        self,
        default_inputs: Dict[str, _promise.Input] = None,
        fixed_inputs: Dict[str, Any] = None,
        schedule=None,
        role=None,
        notifications=None,
        labels=None,
        annotations=None,
        assumable_iam_role=None,
        kubernetes_service_account=None,
        raw_output_data_prefix=None,
    ):
        """
        This method will create a launch plan object that can execute this workflow.
        :param dict[Text,flytekit.common.promise.Input] default_inputs:
        :param dict[Text,T] fixed_inputs:
        :param flytekit.models.schedule.Schedule schedule: A schedule on which to execute this launch plan.
        :param Text role: Deprecated. Use assumable_iam_role instead.
        :param list[flytekit.models.common.Notification] notifications: A list of notifications to enact by default for
        this launch plan.
        :param flytekit.models.common.Labels labels:
        :param flytekit.models.common.Annotations annotations:
        :param cls: This parameter can be used by users to define an extension of a launch plan to instantiate.  The
        class provided should be a subclass of flytekit.common.launch_plan.SdkLaunchPlan.
        :param Text assumable_iam_role: The IAM role to execute the workflow with.
        :param Text kubernetes_service_account: The kubernetes service account to execute the workflow with.
        :param Text raw_output_data_prefix: Bucket for offloaded data
        :rtype: flytekit.common.launch_plan.SdkRunnableLaunchPlan
        """
        # TODO: Actually ensure the parameters conform.
        if role and (assumable_iam_role or kubernetes_service_account):
            raise ValueError("Cannot set both role and auth. Role is deprecated, use auth instead.")
        fixed_inputs = fixed_inputs or {}
        merged_default_inputs = {v.name: v for v in self._workflow_inputs if v.name not in fixed_inputs}
        merged_default_inputs.update(default_inputs or {})

        if role:
            assumable_iam_role = role  # For backwards compatibility
        auth_role = _common_models.AuthRole(
            assumable_iam_role=assumable_iam_role, kubernetes_service_account=kubernetes_service_account,
        )

        raw_output_config = _common_models.RawOutputDataConfig(raw_output_data_prefix or "")

        return _launch_plan.SdkRunnableLaunchPlan(
            sdk_workflow=self,
            default_inputs={
                k: user_input.rename_and_return_reference(k) for k, user_input in _six.iteritems(merged_default_inputs)
            },
            fixed_inputs=fixed_inputs,
            schedule=schedule,
            notifications=notifications,
            labels=labels,
            annotations=annotations,
            auth_role=auth_role,
            raw_output_data_config=raw_output_config,
        )

    def to_flyte_idl(self) -> _core_workflow_pb2.WorkflowTemplate:
        return self.flyte_workflow.to_flyte_idl()


def build_sdk_workflow_from_metaclass(metaclass, on_failure=None):
    """
    :param T metaclass: This is the user-defined workflow class, prior to decoration.
    :param on_failure flytekit.models.core.workflow.WorkflowMetadata.OnFailurePolicy: [Optional] The execution policy when the workflow detects a failure.
    :rtype: SdkWorkflow
    """
    inputs, outputs, nodes = _discover_workflow_components(metaclass)
    metadata = _workflow_models.WorkflowMetadata(on_failure=on_failure if on_failure else None)

    return PythonWorkflow.construct_from_class_definition(
        inputs=[i for i in sorted(inputs, key=lambda x: x.name)],
        outputs=[o for o in sorted(outputs, key=lambda x: x.name)],
        nodes=[n for n in sorted(nodes, key=lambda x: x.id)],
        metadata=metadata,
    )


def _discover_workflow_components(workflow_class):
    """
    This task iterates over the attributes of a user-defined class in order to return a list of inputs, outputs and
    nodes.
    :param class workflow_class: User-defined class with task instances as attributes.
    :rtype: (list[flytekit.common.promise.Input], list[Output], list[flytekit.common.nodes.SdkNode])
    """

    inputs = []
    outputs = []
    nodes = []

    to_visit_objs = _queue.Queue()
    top_level_attributes = set()
    for attribute_name in dir(workflow_class):
        to_visit_objs.put((attribute_name, getattr(workflow_class, attribute_name)))
        top_level_attributes.add(attribute_name)

    # For all task instances defined within the workflow, bind them to this specific workflow and hook-up to the
    # engine (when available)
    visited_obj_ids = set()
    while not to_visit_objs.empty():
        attribute_name, current_obj = to_visit_objs.get()

        current_obj_id = id(current_obj)
        if current_obj_id in visited_obj_ids:
            continue
        visited_obj_ids.add(current_obj_id)

        if isinstance(current_obj, _nodes.SdkNode):
            # TODO: If an attribute name is on the form node_name[index], the resulting
            # node name might not be correct.
            nodes.append(current_obj.assign_id_and_return(attribute_name))
        elif isinstance(current_obj, _promise.Input):
            if attribute_name is None or attribute_name not in top_level_attributes:
                raise _user_exceptions.FlyteValueException(
                    attribute_name, "Detected workflow input specified outside of top level.",
                )
            inputs.append(current_obj.rename_and_return_reference(attribute_name))
        elif isinstance(current_obj, Output):
            if attribute_name is None or attribute_name not in top_level_attributes:
                raise _user_exceptions.FlyteValueException(
                    attribute_name, "Detected workflow output specified outside of top level.",
                )
            outputs.append(current_obj.rename_and_return_reference(attribute_name))
        elif isinstance(current_obj, list) or isinstance(current_obj, set) or isinstance(current_obj, tuple):
            for idx, value in enumerate(current_obj):
                to_visit_objs.put((_assign_indexed_attribute_name(attribute_name, idx), value))
        elif isinstance(current_obj, dict):
            # Visit dictionary keys.
            for key in current_obj.keys():
                to_visit_objs.put((_assign_indexed_attribute_name(attribute_name, key), key))
            # Visit dictionary values.
            for key, value in _six.iteritems(current_obj):
                to_visit_objs.put((_assign_indexed_attribute_name(attribute_name, key), value))
    return inputs, outputs, nodes


def _assign_indexed_attribute_name(attribute_name, index):
    return "{}[{}]".format(attribute_name, index)
