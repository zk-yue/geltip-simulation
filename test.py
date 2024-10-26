from yarok import Platform
from yarok.examples.grasp_rope_world import GraspRopeWorld, GraspRopeWorld

Platform.create({
    'world': GraspRopeWorld,
    'behaviour': GraspRoleBehaviour
}).run()