#!/usr/bin/perl
#
# Copyright 2010, Todd Stumpf, aka Nine At A Time Media
#
# Author: (>>>USER_NAME<<<) <(>>>LOGIN_NAME<<<)@(>>>HOST_ADDR<<<)>
# Created: (>>>DATE<<<)
#
package (>>>package_name<<<);

BEGIN {
    use Exporter;
    our ($VERSION, @ISA, @EXPORT, @EXPORT_OK, %EXPORT_TAGS);

    $VERSION = '0.1.0';
    @ISA = qw(Exporter);
    @EXPORT = qw();
    %EXPORT_TAGS = ();
    @EXPORT_OK = qw(export1 export2 export3);
}

(>>>POINT<<<)

use strict;
use Carp;

sub new {
    # Does it get any more generic than this?  I thought not...
    my $this = shift;
    my $class = ref($this) || $this;
    my $self = {};
    bless $self, $class;
    $self->initialize();
    return $self;
}

sub initialize {
    die "This should never be called.";
}

__END__
=head1 NAME

(>>>package_name<<<) - one line description

=head1 SYNOPSIS

  use (>>>package_name<<<) qw(export2);
  code
  sample
  ...
  and
  such

=head1 DESCRIPTION

longhand description of package.

=head1 EXPORT

=over 12

=item export1

Description.

=item Exportable

C<freeze thaw cmpStr cmpStrHard safeFreeze>.

=back

=head1 User API

=over 12

=item C<export1>

Description of stuff.  Use C<export1> to generate a reference.

=item C<export2>

=back

=head1 Developer API

A full walkthru of using the code, including sample code.

>>>TEMPLATE-DEFINITION-SECTION<<<
("package_name" "Package Name: ")
